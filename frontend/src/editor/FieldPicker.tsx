import { Combobox, Option, OptionGroup } from '@fluentui/react-components'
import { createContext, useContext, useMemo, useState } from 'react'

import type { Catalog, JsonSchema } from '../api/types'
import { type Key, type Params, t, useI18n } from '../i18n'
import { describeTypes, type FieldInfo, listFields } from './schemaPaths'

/** What expressions in the current position can reference. */
export interface FieldScope {
  catalog: Catalog
  schema: JsonSchema | undefined
  input: FieldInfo[]
  vars: string[]
  nodes: string[]
  item?: { schema: JsonSchema | undefined; fields: FieldInfo[] }
  outer?: { schema: JsonSchema | undefined; fields: FieldInfo[] }
}

export const ScopeContext = createContext<FieldScope | null>(null)

export function useScope(): FieldScope {
  const scope = useContext(ScopeContext)
  if (!scope) throw new Error('FieldScope missing')
  return scope
}

/** Scope for the `where` / `select` of an aggregate over elements described by `element`. */
export function itemScope(scope: FieldScope, element: JsonSchema | undefined): FieldScope {
  return {
    ...scope,
    outer: scope.item,
    item: { schema: element, fields: listFields(element, '$.item') },
  }
}

export interface FieldChoice {
  path: string
  types: string[]
  format?: string
  many?: boolean
  enum?: unknown[]
}

export function allChoices(
  scope: FieldScope,
  tr: (key: Key, params?: Params) => string = t,
): { group: string; items: (FieldChoice & { hint: string })[] }[] {
  const fromFields = (fields: FieldInfo[]) => fields.map((f) => ({ ...f, hint: describeTypes(f) }))
  const groups = []
  if (scope.item) {
    groups.push({
      group: tr('fields.currentItem'),
      items: [{ path: '$.item', types: [], hint: tr('fields.wholeItem') }, ...fromFields(scope.item.fields)],
    })
  }
  if (scope.outer) {
    groups.push({
      group: tr('fields.outerItem'),
      items: [{ path: '$.outer', types: [], hint: tr('fields.wholeItem') }, ...fromFields(scope.outer.fields.map((f) => ({ ...f, path: f.path.replace(/^\$\.item/, '$.outer') })))],
    })
  }
  groups.push({ group: tr('fields.input'), items: fromFields(scope.input) })
  groups.push({
    group: tr('fields.vars'),
    items: scope.vars.map((v) => ({ path: `$.vars.${v}`, types: [], hint: tr('fields.varsHint') })),
  })
  groups.push({
    group: tr('fields.nodes'),
    items: scope.nodes.map((n) => ({ path: `$.nodes.${n}.outcome`, types: ['string'], hint: 'pass / fail' })),
  })
  groups.push({
    group: tr('fields.meta'),
    items: scope.catalog.metaKeys.map((k) => ({ path: `$.meta.${k}`, types: ['string'], hint: tr('fields.metaHint') })),
  })
  return groups
}

export function findChoice(scope: FieldScope, path: string): FieldChoice | undefined {
  for (const g of allChoices(scope)) {
    const hit = g.items.find((i) => i.path === path)
    if (hit) return hit
  }
  return undefined
}

/**
 * Searchable picker of references. Free text is accepted (e.g. a path the schema does not
 * declare yet): the backend type-check reports it at validation time.
 */
export function FieldPicker({
  value,
  onChange,
  filter,
  placeholder,
  ariaLabel,
}: {
  value: string
  onChange: (path: string) => void
  filter?: (choice: FieldChoice) => boolean
  placeholder?: string
  ariaLabel?: string
}) {
  const scope = useScope()
  const { t: tr } = useI18n()
  const [query, setQuery] = useState<string | null>(null)
  const groups = useMemo(() => {
    const q = (query ?? '').toLowerCase()
    return allChoices(scope, tr)
      .map((g) => ({
        ...g,
        items: g.items.filter((i) => (!filter || filter(i)) && (!q || i.path.toLowerCase().includes(q))),
      }))
      .filter((g) => g.items.length > 0)
  }, [scope, query, filter, tr])

  return (
    <Combobox
      aria-label={ariaLabel ?? tr('fields.label')}
      className="field-picker"
      freeform
      placeholder={placeholder ?? tr('fields.placeholder')}
      value={query ?? value}
      selectedOptions={value ? [value] : []}
      onChange={(e) => setQuery(e.target.value)}
      onOptionSelect={(_, d) => {
        if (d.optionValue) onChange(d.optionValue)
        setQuery(null)
      }}
      onBlur={() => {
        if (query !== null && query.startsWith('$.') && query !== value) onChange(query)
        setQuery(null)
      }}
    >
      {groups.map((g) => (
        <OptionGroup key={g.group} label={g.group}>
          {g.items.slice(0, 200).map((i) => (
            <Option key={i.path} value={i.path} text={i.path}>
              <span className="option-path">{i.path}</span>
              <span className="option-hint" aria-hidden="true">{i.hint}</span>
            </Option>
          ))}
        </OptionGroup>
      ))}
    </Combobox>
  )
}
