// Field listing over a JSON Schema, for field pickers and type-aware operator lists.
// Mirrors the resolution rules of backend/src/minos/schema/paths.py (local $ref, anyOf/oneOf/
// allOf flattening, array items) closely enough for the editor; the backend type-check is the
// authority at validation time.

import type { JsonSchema } from '../api/types'
import { t } from '../i18n'

export interface FieldInfo {
  /** Reference as used in expressions, e.g. `$.input.courses[*].cfu`. */
  path: string
  /** Last segment, for display. */
  name: string
  depth: number
  types: string[]
  format?: string
  required: boolean
  /** True when the path crosses a `[*]`: the value is a list of such values. */
  many: boolean
  enum?: unknown[]
}

type Schema = Record<string, unknown>

function deref(root: Schema, schema: Schema, seen = 0): Schema[] {
  if (seen > 32) return [schema]
  const ref = schema.$ref
  if (typeof ref === 'string' && ref.startsWith('#/')) {
    let node: unknown = root
    for (const part of ref.slice(2).split('/')) {
      node = (node as Schema | undefined)?.[part.replace(/~1/g, '/').replace(/~0/g, '~')]
    }
    return node && typeof node === 'object' ? deref(root, node as Schema, seen + 1) : []
  }
  const combos = ['anyOf', 'oneOf', 'allOf'].flatMap((k) => (Array.isArray(schema[k]) ? (schema[k] as Schema[]) : []))
  if (combos.length > 0) {
    const shaped = combos.filter((c) => 'type' in c || 'properties' in c || 'items' in c || '$ref' in c)
    const own = 'type' in schema || 'properties' in schema || 'items' in schema ? [schema] : []
    return [...own, ...shaped.flatMap((c) => deref(root, c, seen + 1))]
  }
  return [schema]
}

function typesOf(candidates: Schema[]): string[] {
  const out = new Set<string>()
  for (const s of candidates) {
    const t = s.type
    if (Array.isArray(t)) t.forEach((x) => out.add(String(x)))
    else if (typeof t === 'string') out.add(t)
    else if (s.properties) out.add('object')
    else if (s.items) out.add('array')
  }
  return [...out]
}

function merged(candidates: Schema[], key: 'properties'): Record<string, Schema> {
  return Object.assign({}, ...candidates.map((c) => (c[key] as Record<string, Schema> | undefined) ?? {}))
}

/** List every field reachable in `schema`, depth-first, prefixed with `root`. */
export function listFields(schema: JsonSchema | undefined, root = '$.input', maxDepth = 6): FieldInfo[] {
  if (!schema) return []
  const rootSchema = schema as Schema
  const out: FieldInfo[] = []

  function walk(node: Schema, path: string, depth: number, many: boolean) {
    if (depth > maxDepth) return
    const candidates = deref(rootSchema, node)
    const props = merged(candidates, 'properties')
    const required = new Set(candidates.flatMap((c) => (Array.isArray(c.required) ? (c.required as string[]) : [])))
    // Alphabetical: PostgreSQL (JSONB) does not keep key order, so this keeps lists stable.
    for (const [name, child] of Object.entries(props).sort(([a], [b]) => a.localeCompare(b))) {
      const childCandidates = deref(rootSchema, child)
      const childPath = /^[A-Za-z_][A-Za-z0-9_-]*$/.test(name) ? `${path}.${name}` : `${path}["${name}"]`
      const types = typesOf(childCandidates)
      const format = childCandidates.map((c) => c.format).find((f): f is string => typeof f === 'string')
      const enumValues = childCandidates.map((c) => c.enum).find(Array.isArray)
      out.push({ path: childPath, name, depth, types, format, required: required.has(name), many, enum: enumValues })
      if (types.includes('object') || childCandidates.some((c) => c.properties)) {
        walk(child, childPath, depth + 1, many)
      }
      if (types.includes('array')) {
        const items = childCandidates.map((c) => c.items).find((i) => i && typeof i === 'object') as Schema | undefined
        if (items) walk(items, `${childPath}[*]`, depth + 1, true)
      }
    }
  }

  walk(rootSchema, root, 0, false)
  return out
}

/** Schema of the elements of the array at `path` (`$.input.courses` -> course schema). */
export function elementSchema(schema: JsonSchema | undefined, path: string): JsonSchema | undefined {
  if (!schema || !path.startsWith('$.input')) return undefined
  const rootSchema = schema as Schema
  let node: Schema[] = deref(rootSchema, rootSchema)
  const segments = path.slice('$.input'.length).match(/\.[A-Za-z_][A-Za-z0-9_-]*|\["[^"]+"\]|\[\*\]|\[-?\d+\]/g) ?? []
  for (const seg of segments) {
    if (seg === '[*]' || /^\[-?\d+\]$/.test(seg)) {
      node = node.flatMap((c) => (c.items && typeof c.items === 'object' ? deref(rootSchema, c.items as Schema) : []))
    } else {
      const key = seg.startsWith('.') ? seg.slice(1) : seg.slice(2, -2)
      node = node.flatMap((c) => {
        const p = (c.properties as Record<string, Schema> | undefined)?.[key]
        return p ? deref(rootSchema, p) : []
      })
    }
  }
  const items = node.map((c) => c.items).find((i) => i && typeof i === 'object')
  if (items) return { ...(items as Schema), $defs: rootSchema.$defs }
  return undefined
}

export function describeTypes(field: Pick<FieldInfo, 'types' | 'format' | 'many'>): string {
  const base = field.types.filter((type) => type !== 'null').join(' | ') || t('expr.anyType')
  const fmt = field.format ? ` (${field.format})` : ''
  return field.many ? t('expr.listOf', { type: `${base}${fmt}` }) : `${base}${fmt}`
}
