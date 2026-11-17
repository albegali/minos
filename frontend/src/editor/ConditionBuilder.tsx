import { Button, Dropdown, Option, ToggleButton } from '@fluentui/react-components'
import { Add16Regular, Delete16Regular } from '@fluentui/react-icons'

import type { OperatorSpec } from '../api/types'
import { useI18n } from '../i18n'
import {
  blankComparison,
  type Expr,
  isComparison,
  isFn,
  isGroup,
  isNot,
  isRef,
  type OpExpr,
  operands,
  RANGE,
  toggleNot,
  UNARY,
} from './expr'
import { ExpressionEditor, type ValueHint } from './ExpressionEditor'
import { findChoice, useScope } from './FieldPicker'

function useLeftHint(left: Expr): ValueHint {
  const scope = useScope()
  if (isRef(left)) {
    const choice = findChoice(scope, left.ref)
    if (choice) return { types: choice.types, format: choice.format, enum: choice.enum }
  }
  if (isFn(left)) {
    const spec = scope.catalog.functions.find((f) => f.fn === left.fn)
    if (spec && spec.returns !== 'any') return { types: [spec.returns] }
  }
  return {}
}

function operatorFits(op: OperatorSpec, hint: ValueHint): boolean {
  if (!['compare', 'range', 'unary'].includes(op.kind) || op.op === 'not') return false
  const types = (hint.types ?? []).filter((t) => t !== 'null')
  if (op.formats && types.length > 0 && !op.formats.includes(hint.format ?? '')) return false
  if (!op.types || types.length === 0) return true
  return types.some((t) => op.types?.includes(t === 'integer' ? 'number' : t))
}

function Comparison({ value, onChange }: { value: OpExpr; onChange: (e: Expr) => void }) {
  const scope = useScope()
  const [left, right] = operands(value)
  const hint = useLeftHint(left)
  const ops = scope.catalog.operators.filter((o) => operatorFits(o, hint) || o.op === value.op)
  const spec = scope.catalog.operators.find((o) => o.op === value.op)
  const { t, loc } = useI18n()

  function setOp(op: string) {
    const next = scope.catalog.operators.find((o) => o.op === op)
    if (!next) return
    if (UNARY.has(op)) onChange({ op, arg: left })
    else if (RANGE.has(op)) onChange({ op, left, right: Array.isArray(right) ? right : ['', ''] })
    else if (next.rightList) onChange({ op, left, right: Array.isArray(right) ? right : [] })
    else onChange({ op, left, right: Array.isArray(right) || right === undefined ? '' : right })
  }

  const setLeft = (l: Expr) =>
    onChange(UNARY.has(value.op) ? { op: value.op, arg: l } : { op: value.op, left: l, right })

  let rightEditor = null
  if (RANGE.has(value.op)) {
    const [lo, hi] = Array.isArray(right) ? (right as Expr[]) : ['', '']
    rightEditor = (
      <div className="inline">
        <ExpressionEditor value={lo} hint={hint} modes={['value', 'field', 'calc']} compact
          onChange={(v) => onChange({ op: value.op, left, right: [v, hi] })} />
        <span className="muted">{t('condition.rangeAnd')}</span>
        <ExpressionEditor value={hi} hint={hint} modes={['value', 'field', 'calc']} compact
          onChange={(v) => onChange({ op: value.op, left, right: [lo, v] })} />
      </div>
    )
  } else if (spec?.rightList) {
    rightEditor = <ListValue value={right} hint={hint} onChange={(r) => onChange({ op: value.op, left, right: r })} />
  } else if (!UNARY.has(value.op)) {
    rightEditor = (
      <ExpressionEditor value={right} hint={hint} compact
        modes={spec?.rightLiteral ? ['value'] : ['value', 'field', 'aggregate', 'function', 'calc']}
        onChange={(r) => onChange({ op: value.op, left, right: r })} />
    )
  }

  return (
    <div className="comparison">
      <ExpressionEditor value={left} onChange={setLeft} modes={['field', 'aggregate', 'function', 'calc', 'json']} compact />
      <Dropdown
        aria-label={t('condition.operator')}
        className="op-select"
        value={spec ? loc(spec.label) : value.op}
        selectedOptions={[value.op]}
        onOptionSelect={(_, d) => d.optionValue && setOp(d.optionValue)}
      >
        {ops.map((o) => (
          <Option key={o.op} value={o.op}>
            {loc(o.label) || o.op}
          </Option>
        ))}
      </Dropdown>
      {rightEditor}
    </div>
  )
}

/** Values for `in` / `not in`: a comma-separated list or a field holding a list. */
function ListValue({ value, onChange, hint }: { value: Expr; onChange: (e: Expr) => void; hint: ValueHint }) {
  const { t } = useI18n()
  if (isRef(value)) {
    return <ExpressionEditor value={value} onChange={onChange} modes={['field', 'value']} compact />
  }
  const items = Array.isArray(value) ? value : []
  const numeric = hint.types?.some((type) => type === 'number' || type === 'integer')
  return (
    <div className="inline">
      <input
        aria-label={t('condition.listValues')}
        className="list-input"
        defaultValue={items.join(', ')}
        placeholder={t('condition.listPlaceholder')}
        onBlur={(e) =>
          onChange(
            e.target.value
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
              .map((s) => (numeric && !Number.isNaN(Number(s)) ? Number(s) : s)),
          )
        }
      />
      <Button size="small" appearance="subtle" onClick={() => onChange({ ref: '' })}>
        {t('condition.fromField')}
      </Button>
    </div>
  )
}

function Group({ value, onChange, depth }: { value: OpExpr; onChange: (e: Expr) => void; depth: number }) {
  const children = operands(value)
  const set = (args: Expr[]) => onChange({ op: value.op, args })
  const { t } = useI18n()
  return (
    <div className={`cond-group depth-${depth % 3}`}>
      <div className="cond-group-head">
        <Dropdown
          aria-label={t('condition.combination')}
          size="small"
          className="logic-select"
          value={value.op === 'and' ? t('condition.all') : t('condition.any')}
          selectedOptions={[value.op]}
          onOptionSelect={(_, d) => onChange({ op: d.optionValue, args: children })}
        >
          <Option value="and">{t('condition.all')}</Option>
          <Option value="or">{t('condition.any')}</Option>
        </Dropdown>
      </div>
      {children.map((child, i) => (
        <ConditionBuilder
          key={i}
          value={child}
          depth={depth + 1}
          onChange={(c) => set(children.map((x, j) => (j === i ? c : x)))}
          onRemove={children.length > 1 ? () => set(children.filter((_, j) => j !== i)) : undefined}
        />
      ))}
      <div className="cond-group-actions">
        <Button size="small" appearance="subtle" icon={<Add16Regular />} onClick={() => set([...children, blankComparison()])}>
          {t('condition.addCondition')}
        </Button>
        <Button
          size="small"
          appearance="subtle"
          icon={<Add16Regular />}
          onClick={() => set([...children, { op: value.op === 'and' ? 'or' : 'and', args: [blankComparison()] }])}
        >
          {t('condition.addGroup')}
        </Button>
      </div>
    </div>
  )
}

/**
 * Visual builder for boolean conditions: comparisons, AND/OR groups nested at any depth and
 * NOT on any part. Shapes it does not model (e.g. a boolean aggregate) fall back to the
 * generic expression editor, so no condition is ever unrepresentable.
 */
export function ConditionBuilder({
  value,
  onChange,
  onRemove,
  depth = 0,
  root = false,
}: {
  value: Expr
  onChange: (e: Expr) => void
  onRemove?: () => void
  depth?: number
  root?: boolean
}) {
  const negated = isNot(value)
  const inner = negated ? operands(value as OpExpr)[0] : value
  const update = (e: Expr) => onChange(negated ? { op: 'not', arg: e } : e)
  const { t } = useI18n()

  let body
  if (isGroup(inner)) body = <Group value={inner} onChange={update} depth={depth} />
  else if (isComparison(inner)) body = <Comparison value={inner} onChange={update} />
  else body = <ExpressionEditor value={inner} onChange={update} modes={['aggregate', 'field', 'function', 'json']} compact />

  return (
    <div className="cond">
      <div className="cond-tools">
        <ToggleButton size="small" checked={negated} onClick={() => onChange(toggleNot(value))} aria-label={t('condition.negation')}>
          {t('condition.not')}
        </ToggleButton>
        {onRemove && (
          <Button size="small" appearance="subtle" aria-label={t('condition.remove')} icon={<Delete16Regular />} onClick={onRemove} />
        )}
      </div>
      <div className="cond-body">{body}</div>
      {root && !isGroup(inner) && (
        <Button
          size="small"
          appearance="subtle"
          icon={<Add16Regular />}
          onClick={() => onChange({ op: 'and', args: [value, blankComparison()] })}
        >
          {t('condition.add')}
        </Button>
      )}
    </div>
  )
}
