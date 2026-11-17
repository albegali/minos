// Entities used as field types: `{"$ref": "entity:Course"}` in a schema as written, and
// `#/$defs/entity:Course@2` in the resolved form returned by the API
// (see backend/src/minos/schema/refs.py).

import type { JsonSchema } from '../api/types'

type Schema = Record<string, unknown>

// Same grammar as the backend (schema/refs.py): key up to 100 characters, versions from 1.
const AUTHORED = /^entity:([A-Za-z0-9][A-Za-z0-9_.-]{0,99})(?:@([1-9][0-9]*))?$/
const RESOLVED = /^#\/\$defs\/entity:([A-Za-z0-9][A-Za-z0-9_.-]{0,99})@([1-9][0-9]*)$/

export interface EntityLink {
  entity: string
  version?: number
}

/** The entity a (resolved or authored) sub-schema stands for, if it is a reference. */
export function entityOf(schema: unknown): EntityLink | undefined {
  const ref = (schema as Schema | undefined)?.$ref
  if (typeof ref !== 'string') return undefined
  const [, entity, version] = RESOLVED.exec(ref) ?? AUTHORED.exec(ref) ?? []
  if (!entity) return undefined
  return version ? { entity, version: Number(version) } : { entity }
}

/** Copy of `schema` with every entity reference unpinned, so that saving it moves each one to
 * the referenced entity's latest version. */
// Same rules as backend/src/minos/schema/refs.py: data keywords are skipped, but the names
// inside these maps are the user's (a property may be called "default").
const DATA_KEYS = new Set(['enum', 'const', 'default', 'examples'])
const SCHEMA_MAPS = new Set(['properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'])

export function unpinRefs(schema: JsonSchema): JsonSchema {
  const walk = (node: unknown, key?: string): unknown => {
    if (key && DATA_KEYS.has(key)) return node
    if (Array.isArray(node)) return node.map((n) => walk(n))
    if (!node || typeof node !== 'object') return node
    const out: Schema = {}
    for (const [k, v] of Object.entries(node as Schema)) {
      out[k] =
        SCHEMA_MAPS.has(k) && v && typeof v === 'object' && !Array.isArray(v)
          ? Object.fromEntries(Object.entries(v as Schema).map(([name, sub]) => [name, walk(sub)]))
          : walk(v, k)
    }
    const link = entityOf(node)
    if (link && typeof out.$ref === 'string' && out.$ref.startsWith('entity:')) out.$ref = `entity:${link.entity}`
    return out
  }
  return walk(schema) as JsonSchema
}

/** A top-level field whose type is an entity (or a list of an entity). */
export interface RefRow {
  name: string
  entity: string
  many: boolean
  required: boolean
  /** The reference as stored, kept when the entity does not change (keeps its version). */
  ref?: string
}

function rowOf(name: string, prop: Schema, required: boolean): RefRow | undefined {
  const items = prop.type === 'array' ? (prop.items as Schema | undefined) : undefined
  const target = items ?? prop
  const link = entityOf(target)
  if (!link || typeof target.$ref !== 'string' || !target.$ref.startsWith('entity:')) return undefined
  return { name, entity: link.entity, many: Boolean(items), required, ref: target.$ref }
}

/** The entity-typed top-level fields of an authored schema. */
export function refRows(schema: JsonSchema | undefined): RefRow[] {
  const props = ((schema as Schema | undefined)?.properties ?? {}) as Record<string, Schema>
  const required = new Set(((schema as Schema | undefined)?.required as string[] | undefined) ?? [])
  return Object.entries(props).flatMap(([name, prop]) => {
    const row = prop && typeof prop === 'object' ? rowOf(name, prop, required.has(name)) : undefined
    return row ? [row] : []
  })
}

/** `base` with its entity-typed top-level fields replaced by `rows`; other fields untouched. */
export function applyRefRows(base: JsonSchema | undefined, rows: RefRow[]): JsonSchema {
  const schema: Schema = { ...(base ?? {}) }
  const previous = new Set(refRows(base).map((r) => r.name))
  const props: Record<string, unknown> = Object.fromEntries(
    Object.entries((schema.properties as Schema | undefined) ?? {}).filter(([name]) => !previous.has(name)),
  )
  const required = new Set(((schema.required as string[] | undefined) ?? []).filter((n) => !previous.has(n)))
  for (const row of rows) {
    const name = row.name.trim()
    if (!name || !row.entity) continue
    const kept = row.ref && entityOf({ $ref: row.ref })?.entity === row.entity ? row.ref : undefined
    const ref = { $ref: kept ?? `entity:${row.entity}` }
    props[name] = row.many ? { type: 'array', items: ref } : ref
    if (row.required) required.add(name)
  }
  schema.type ??= 'object'
  schema.properties = props
  if (required.size > 0) schema.required = [...required].sort()
  else delete schema.required
  return schema as JsonSchema
}
