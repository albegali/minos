import { Button, Checkbox, Dropdown, Input, Option, Tooltip } from '@fluentui/react-components'
import { Add16Regular, Dismiss16Regular } from '@fluentui/react-icons'

import { JsonField } from '../components/forms'
import { ConditionBuilder } from './ConditionBuilder'
import {
  blankComparison,
  type Expr,
  isFn,
  isOp,
  isRef,
  literalText,
  operands,
  parseLiteral,
} from './expr'
import { type FieldChoice, FieldPicker, itemScope, ScopeContext, useScope } from './FieldPicker'
import { compact } from '../util'
import { elementSchema } from './schemaPaths'

export type Mode = 'field' | 'value' | 'aggregate' | 'function' | 'calc' | 'json'

const MODE_LABEL: Record<Mode, string> = {
  field: 'Campo',
  value: 'Valore',
  aggregate: 'Su una lista',
  function: 'Funzione',
  calc: 'Calcolo',
  json: 'JSON',
}

const ARITH = ['+', '-', '*', '/', '%']

export function modeOf(e: Expr, aggregates: Set<string>): Mode {
  if (isRef(e)) return 'field'
  if (isFn(e)) return aggregates.has(e.fn) ? 'aggregate' : 'function'
  if (isOp(e) && ARITH.includes(e.op)) return 'calc'
  if (e === null || ['string', 'number', 'boolean'].includes(typeof e)) return 'value'
  return 'json'
}

export interface ValueHint {
  types?: string[]
  format?: string
  enum?: unknown[]
}

function initial(mode: Mode): Expr {
  switch (mode) {
    case 'field':
      return { ref: '' }
    case 'value':
      return ''
    case 'aggregate':
      return { fn: 'count', args: [{ ref: '' }] }
    case 'function':
      return { fn: 'coalesce', args: [{ ref: '' }, 0] }
    case 'calc':
      return { op: '+', args: [{ ref: '' }, 0] }
    case 'json':
      return null
  }
}

/** Element schema of the list an aggregate iterates over, when the schema knows it. */
export function useElementSchema(source: Expr) {
  const scope = useScope()
  if (!isRef(source)) return undefined
  const ref = source.ref
  if (ref.startsWith('$.input')) {
    if (ref.includes('[*]')) {
      // `$.input.courses[*].lessons` → elements of lessons; `$.input.courses[*]` → a course
      const trimmed = ref.endsWith('[*]') ? ref.slice(0, -3) : ref
      return ref.endsWith('[*]') ? elementSchema(scope.schema, trimmed) : elementSchema(scope.schema, ref)
    }
    return elementSchema(scope.schema, ref)
  }
  for (const [root, s] of [['$.item', scope.item], ['$.outer', scope.outer]] as const) {
    if (s && ref.startsWith(root)) return elementSchema(s.schema, ref.replace(root, '$.input'))
  }
  return undefined
}

function ValueInput({ value, onChange, hint }: { value: Expr; onChange: (e: Expr) => void; hint?: ValueHint }) {
  if (hint?.enum && hint.enum.length > 0) {
    const current = literalText(value)
    return (
      <Dropdown
        aria-label="Valore"
        className="value-input"
        value={current}
        selectedOptions={[current]}
        onOptionSelect={(_, d) => onChange(hint.enum?.find((x) => literalText(x) === d.optionValue) ?? d.optionValue)}
      >
        {hint.enum.map((x) => (
          <Option key={literalText(x)} value={literalText(x)}>
            {literalText(x)}
          </Option>
        ))}
      </Dropdown>
    )
  }
  if (hint?.types?.length === 1 && hint.types[0] === 'boolean') {
    return <Checkbox label="vero" checked={value === true} onChange={(_, d) => onChange(Boolean(d.checked))} />
  }
  const isDate = hint?.format === 'date' || hint?.format === 'date-time'
  return (
    <Input
      aria-label="Valore"
      className="value-input"
      type={isDate ? 'date' : 'text'}
      value={isDate ? literalText(value).slice(0, 10) : literalText(value)}
      placeholder={hint?.types?.includes('number') || hint?.types?.includes('integer') ? 'numero' : 'valore'}
      onChange={(_, d) => onChange(isDate ? d.value : parseLiteral(d.value, hint?.types))}
    />
  )
}

function ArgList({
  args,
  onChange,
  min,
  max,
}: {
  args: Expr[]
  onChange: (args: Expr[]) => void
  min: number
  max: number
}) {
  return (
    <div className="arg-list">
      {args.map((a, i) => (
        <div key={i} className="arg-row">
          <ExpressionEditor value={a} onChange={(v) => onChange(args.map((x, j) => (j === i ? v : x)))} compact />
          {args.length > min && (
            <Button
              appearance="subtle"
              size="small"
              aria-label="Rimuovi argomento"
              icon={<Dismiss16Regular />}
              onClick={() => onChange(args.filter((_, j) => j !== i))}
            />
          )}
        </div>
      ))}
      {args.length < max && (
        <Button size="small" appearance="subtle" icon={<Add16Regular />} onClick={() => onChange([...args, 0])}>
          Argomento
        </Button>
      )}
    </div>
  )
}

function arity(spec: number | string | undefined): [number, number] {
  if (typeof spec === 'number') return [spec, spec]
  if (spec === '1+') return [1, 8]
  if (spec === '1-2') return [1, 2]
  return [0, 8]
}

const isList = (c: FieldChoice) => Boolean(c.many) || c.types.includes('array') || c.types.length === 0

function AggregateEditor({ value, onChange }: { value: { fn: string; args?: Expr[]; where?: Expr; select?: Expr }; onChange: (e: Expr) => void }) {
  const scope = useScope()
  const aggregates = scope.catalog.functions.filter((f) => f.aggregate)
  const source = value.args?.[0] ?? { ref: '' }
  const element = useElementSchema(source)
  const inner = itemScope(scope, element)
  const set = (patch: Record<string, unknown>) => onChange(compact({ ...value, ...patch }))
  return (
    <div className="aggregate">
      <div className="inline">
        <Dropdown
          aria-label="Funzione sulla lista"
          className="fn-select"
          value={aggregates.find((f) => f.fn === value.fn)?.label.it ?? value.fn}
          selectedOptions={[value.fn]}
          onOptionSelect={(_, d) => set({ fn: d.optionValue })}
        >
          {aggregates.map((f) => (
            <Option key={f.fn} value={f.fn}>
              {f.label.it ?? f.fn}
            </Option>
          ))}
        </Dropdown>
        <span className="muted">di</span>
        {isRef(source) ? (
          <FieldPicker
            ariaLabel="Lista"
            placeholder="Scegli una lista"
            value={source.ref}
            filter={isList}
            onChange={(ref) => set({ args: [{ ref }] })}
          />
        ) : (
          <ExpressionEditor value={source} onChange={(v) => set({ args: [v] })} compact />
        )}
      </div>
      <ScopeContext.Provider value={inner}>
        <Checkbox
          label="Solo gli elementi che rispettano una condizione"
          checked={value.where !== undefined}
          onChange={(_, d) => set({ where: d.checked ? blankComparison() : undefined })}
        />
        {value.where !== undefined && (
          <div className="nested">
            <ConditionBuilder value={value.where} onChange={(w) => set({ where: w })} />
          </div>
        )}
        {value.fn !== 'count' && value.fn !== 'filter' && (
          <>
            <Checkbox
              label="Usa un valore calcolato da ogni elemento"
              checked={value.select !== undefined}
              onChange={(_, d) => set({ select: d.checked ? { ref: '$.item' } : undefined })}
            />
            {value.select !== undefined && (
              <div className="nested">
                <ExpressionEditor value={value.select} onChange={(v) => set({ select: v })} compact />
              </div>
            )}
          </>
        )}
      </ScopeContext.Provider>
    </div>
  )
}

/**
 * Editor for any expression: a field, a literal, an aggregate over a list (with filter and
 * projection), a function, an arithmetic calculation, or raw JSON as an escape hatch.
 */
export function ExpressionEditor({
  value,
  onChange,
  modes,
  hint,
  compact = false,
}: {
  value: Expr
  onChange: (e: Expr) => void
  modes?: Mode[]
  hint?: ValueHint
  compact?: boolean
}) {
  const scope = useScope()
  const aggregateNames = new Set(scope.catalog.functions.filter((f) => f.aggregate).map((f) => f.fn))
  const mode = modeOf(value, aggregateNames)
  const allowed = modes ?? (['field', 'value', 'aggregate', 'function', 'calc', 'json'] as Mode[])
  const choices = allowed.includes(mode) ? allowed : [...allowed, mode]

  let body
  if (mode === 'field' && isRef(value)) {
    body = <FieldPicker value={value.ref} onChange={(ref) => onChange({ ref })} />
  } else if (mode === 'value') {
    body = <ValueInput value={value} onChange={onChange} hint={hint} />
  } else if (mode === 'aggregate' && isFn(value)) {
    body = <AggregateEditor value={value} onChange={onChange} />
  } else if (mode === 'function' && isFn(value)) {
    const fns = scope.catalog.functions.filter((f) => !f.aggregate)
    const spec = fns.find((f) => f.fn === value.fn)
    const [min, max] = arity(spec?.args)
    body = (
      <div className="stack-tight">
        <Dropdown
          aria-label="Funzione"
          className="fn-select"
          value={spec?.label.it ?? value.fn}
          selectedOptions={[value.fn]}
          onOptionSelect={(_, d) => {
            const next = fns.find((f) => f.fn === d.optionValue)
            const [lo] = arity(next?.args)
            const args = [...(value.args ?? [])].slice(0, Math.max(lo, 1))
            while (args.length < lo) args.push({ ref: '' })
            onChange({ fn: d.optionValue, args: lo === 0 ? [] : args })
          }}
        >
          {fns.map((f) => (
            <Option key={f.fn} value={f.fn}>
              {f.label.it ?? f.fn}
            </Option>
          ))}
        </Dropdown>
        <ArgList args={value.args ?? []} min={min} max={max} onChange={(args) => onChange({ ...value, args })} />
      </div>
    )
  } else if (mode === 'calc' && isOp(value)) {
    body = (
      <div className="stack-tight">
        <Dropdown
          aria-label="Operazione"
          className="op-select"
          value={value.op}
          selectedOptions={[value.op]}
          onOptionSelect={(_, d) => onChange({ op: d.optionValue, args: operands(value) })}
        >
          {ARITH.map((op) => (
            <Option key={op} value={op}>
              {op}
            </Option>
          ))}
        </Dropdown>
        <ArgList args={operands(value)} min={2} max={8} onChange={(args) => onChange({ op: value.op, args })} />
      </div>
    )
  } else {
    body = <JsonField label="Espressione (JSON)" value={value} onValid={onChange} rows={compact ? 3 : 6} />
  }

  return (
    <div className={compact ? 'expr expr-compact' : 'expr'}>
      {choices.length > 1 && (
        <Tooltip content="Tipo di espressione" relationship="label">
          <Dropdown
            aria-label="Tipo di espressione"
            className="mode-select"
            size="small"
            value={MODE_LABEL[mode]}
            selectedOptions={[mode]}
            onOptionSelect={(_, d) => {
              const m = d.optionValue as Mode
              if (m !== mode) onChange(initial(m))
            }}
          >
            {choices.map((m) => (
              <Option key={m} value={m}>
                {MODE_LABEL[m]}
              </Option>
            ))}
          </Dropdown>
        </Tooltip>
      )}
      <div className="expr-body">{body}</div>
    </div>
  )
}
