import {
  Button,
  Checkbox,
  Dropdown,
  Field,
  Input,
  Option,
  Text,
  Tooltip,
} from '@fluentui/react-components'
import {
  Add16Regular,
  ArrowDown16Regular,
  ArrowUp16Regular,
  Delete16Regular,
} from '@fluentui/react-icons'
import { useState } from 'react'
import { useParams } from 'react-router'

import { useRulesets, useVersions } from '../api/hooks'
import { useI18n } from '../i18n'
import type { RgdNode } from '../rgd'
import { formatCell, formatOutput, parseCell, parseOutput } from './cells'
import { describe, type Expr, isRef } from './expr'

const isBlank = (e: Expr) => e === undefined || (isRef(e) && !e.ref)
import { ExpressionEditor, useElementSchema } from './ExpressionEditor'
import { FieldPicker, itemScope, ScopeContext, useScope } from './FieldPicker'

interface Column {
  name: string
  label?: string
}
interface InputColumn extends Column {
  expr: Expr
}
interface Row {
  when: unknown[]
  then: Record<string, unknown>
  priority?: number
  description?: string
}

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/

function uniqueName(base: string, taken: string[]): string {
  let name = base
  for (let i = 2; taken.includes(name); i++) name = `${base}${i}`
  return name
}

/** A cell edited as text; invalid syntax cannot happen (everything parses), so the text is
 * kept while typing and parsed on blur. */
function CellInput({
  value,
  onChange,
  format,
  parse,
  label,
}: {
  value: unknown
  onChange: (v: unknown) => void
  format: (v: unknown) => string
  parse: (t: string) => unknown
  label: string
}) {
  const shown = format(value)
  const [text, setText] = useState<string | null>(null)
  return (
    <input
      aria-label={label}
      className="cell-input"
      value={text ?? shown}
      placeholder="-"
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (text !== null && text !== shown) onChange(parse(text))
        setText(null)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
      }}
    />
  )
}

export function DecisionTableEditor({ node, set }: { node: RgdNode; set: (n: RgdNode) => void }) {
  const scope = useScope()
  const hitPolicies =
    (scope.catalog.nodeTypes.find((m) => m.type === 'decision_table') as { hitPolicies?: { key: string; label: Record<string, string> }[] } | undefined)
      ?.hitPolicies ?? []
  const inputs = (node.inputs as InputColumn[] | undefined) ?? []
  const outputs = (node.outputs as Column[] | undefined) ?? []
  const rules = (node.rules as Row[] | undefined) ?? []
  const hit = (node.hitPolicy as string | undefined) ?? 'first'
  const [openInput, setOpenInput] = useState<number | null>(null)
  const { t, rich, loc } = useI18n()

  const write = (patch: Partial<{ inputs: InputColumn[]; outputs: Column[]; rules: Row[] }>) =>
    set({ ...node, ...patch })
  const setRule = (i: number, rule: Row) => write({ rules: rules.map((r, j) => (j === i ? rule : r)) })
  const move = (i: number, d: number) => {
    const next = [...rules]
    const [r] = next.splice(i, 1)
    if (r) next.splice(i + d, 0, r)
    write({ rules: next })
  }

  return (
    <div className="stack">
      <div className="inline">
        <Field label={t('table.hitPolicy')}>
          <Dropdown
            value={loc(hitPolicies.find((h) => h.key === hit)?.label) || hit}
            selectedOptions={[hit]}
            onOptionSelect={(_, d) => set({ ...node, hitPolicy: d.optionValue })}
          >
            {hitPolicies.map((h) => (
              <Option key={h.key} value={h.key}>
                {loc(h.label) || h.key}
              </Option>
            ))}
          </Dropdown>
        </Field>
        <Field label={t('table.saveIn')} hint={t('table.availableAs', { target: String(node.target ?? '') })}>
          <Input
            value={String(node.target ?? '')}
            onChange={(_, d) => IDENT.test(d.value) && set({ ...node, target: d.value })}
          />
        </Field>
      </div>

      <Text weight="semibold">{t('table.inputColumns')}</Text>
      {inputs.map((col, i) => (
        <div key={i} className="rule-card">
          <div className="inline">
            <Input
              aria-label={t('table.inputName', { n: i + 1 })}
              value={col.label ?? col.name}
              onChange={(_, d) => write({ inputs: inputs.map((c, j) => (j === i ? { ...c, label: d.value } : c)) })}
            />
            <Button size="small" appearance="subtle" onClick={() => setOpenInput(openInput === i ? null : i)}>
              {openInput === i ? t('common.close') : isBlank(col.expr) ? t('table.chooseValue') : describe(col.expr)}
            </Button>
            {inputs.length > 1 && (
              <Button
                size="small"
                appearance="subtle"
                aria-label={t('table.removeInput', { name: col.label ?? col.name })}
                icon={<Delete16Regular />}
                onClick={() =>
                  write({
                    inputs: inputs.filter((_, j) => j !== i),
                    rules: rules.map((r) => ({ ...r, when: r.when.filter((_, j) => j !== i) })),
                  })
                }
              />
            )}
          </div>
          {openInput === i && (
            <ExpressionEditor
              value={col.expr}
              onChange={(expr) => write({ inputs: inputs.map((c, j) => (j === i ? { ...c, expr } : c)) })}
            />
          )}
        </div>
      ))}
      <div className="inline">
        <Button
          size="small"
          icon={<Add16Regular />}
          onClick={() => {
            const name = uniqueName(t('table.inputBase'), inputs.map((c) => c.name))
            write({
              inputs: [...inputs, { name, label: name, expr: { ref: '' } }],
              rules: rules.map((r) => ({ ...r, when: [...r.when, null] })),
            })
            setOpenInput(inputs.length)
          }}
        >
          {t('table.addInput')}
        </Button>
        <Button
          size="small"
          icon={<Add16Regular />}
          onClick={() => {
            const name = uniqueName(t('table.outputBase'), outputs.map((c) => c.name))
            write({ outputs: [...outputs, { name, label: name }] })
          }}
        >
          {t('table.addOutput')}
        </Button>
      </div>

      <div className="dt-scroll">
        <table className="dt" aria-label={t('table.rows')}>
          <thead>
            <tr>
              <th>#</th>
              {inputs.map((c) => (
                <th key={`i-${c.name}`} className="dt-in">
                  {c.label ?? c.name}
                </th>
              ))}
              {outputs.map((c, i) => (
                <th key={`o-${c.name}`} className="dt-out">
                  <input
                    aria-label={t('table.outputName', { n: i + 1 })}
                    className="cell-input head"
                    defaultValue={c.name}
                    onBlur={(e) => {
                      const name = e.target.value.trim()
                      if (!IDENT.test(name) || name === c.name || outputs.some((o) => o.name === name)) return
                      write({
                        outputs: outputs.map((o, j) => (j === i ? { ...o, name, label: name } : o)),
                        rules: rules.map((r) => ({
                          ...r,
                          then: Object.fromEntries(
                            Object.entries(r.then).map(([k, v]) => [k === c.name ? name : k, v]),
                          ),
                        })),
                      })
                    }}
                  />
                </th>
              ))}
              {hit === 'priority' && <th>{t('table.priority')}</th>}
              <th aria-label={t('table.actions')} />
            </tr>
          </thead>
          <tbody>
            {rules.map((rule, i) => (
              <tr key={i}>
                <td className="dt-num">{i + 1}</td>
                {inputs.map((c, j) => (
                  <td key={`i-${c.name}`}>
                    <CellInput
                      label={t('table.cell', { n: i + 1, column: c.label ?? c.name })}
                      value={rule.when[j] ?? null}
                      format={formatCell}
                      parse={parseCell}
                      onChange={(v) => setRule(i, { ...rule, when: rule.when.map((x, k) => (k === j ? v : x)) })}
                    />
                  </td>
                ))}
                {outputs.map((c) => (
                  <td key={`o-${c.name}`} className="dt-out">
                    <CellInput
                      label={t('table.cell', { n: i + 1, column: c.name })}
                      value={rule.then[c.name]}
                      format={formatOutput}
                      parse={parseOutput}
                      onChange={(v) => setRule(i, { ...rule, then: { ...rule.then, [c.name]: v } })}
                    />
                  </td>
                ))}
                {hit === 'priority' && (
                  <td>
                    <CellInput
                      label={t('table.priorityCell', { n: i + 1 })}
                      value={rule.priority ?? 0}
                      format={(v) => String(v)}
                      parse={(t) => Number(t) || 0}
                      onChange={(v) => setRule(i, { ...rule, priority: v as number })}
                    />
                  </td>
                )}
                <td className="dt-actions">
                  <Tooltip content={t('table.up')} relationship="label">
                    <Button size="small" appearance="subtle" icon={<ArrowUp16Regular />} disabled={i === 0} onClick={() => move(i, -1)} />
                  </Tooltip>
                  <Tooltip content={t('table.down')} relationship="label">
                    <Button size="small" appearance="subtle" icon={<ArrowDown16Regular />} disabled={i === rules.length - 1} onClick={() => move(i, 1)} />
                  </Tooltip>
                  <Tooltip content={t('table.removeRow', { n: i + 1 })} relationship="label">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<Delete16Regular />}
                      disabled={rules.length === 1}
                      onClick={() => write({ rules: rules.filter((_, k) => k !== i) })}
                    />
                  </Tooltip>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button
        size="small"
        icon={<Add16Regular />}
        onClick={() => write({ rules: [...rules, { when: inputs.map(() => null), then: {} }] })}
      >
        {t('table.addRow')}
      </Button>
      <Text size={200} className="muted">
        {rich('table.help', {
          c1: <code>EMBA</code>,
          c2: <code>A, B</code>,
          c3: <code>&gt;= 60</code>,
          c4: <code>30..59</code>,
          c5: <code>2027-01-01..2027-12-31</code>,
          c6: <code>!= X</code>,
          c7: <code>$.vars.{t('table.varName')}</code>,
          fail: <b>fail</b>,
        })}
      </Text>
    </div>
  )
}

export function SubRulesetEditor({ node, set }: { node: RgdNode; set: (n: RgdNode) => void }) {
  const { ws = '', rs: current = '' } = useParams()
  const scope = useScope()
  const rulesets = useRulesets(ws)
  const ruleset = String(node.ruleset ?? '')
  const versions = useVersions(ws, ruleset)
  const forEach = node.forEach as Expr | undefined
  const element = useElementSchema(forEach)
  const inner = forEach !== undefined ? itemScope(scope, element) : scope
  const hasInput = 'input' in node
  const { t, rich } = useI18n()

  return (
    <div className="stack">
      <div className="inline">
        <Field label={t('subruleset.ruleset')}>
          <Dropdown
            placeholder={t('subruleset.chooseRuleset')}
            value={ruleset}
            selectedOptions={ruleset ? [ruleset] : []}
            onOptionSelect={(_, d) => set({ ...node, ruleset: d.optionValue, version: '' })}
          >
            {rulesets.data
              ?.filter((r) => r.key !== current)
              .map((r) => (
                <Option key={r.key} value={r.key} text={r.key}>
                  {r.name} ({r.key})
                </Option>
              ))}
          </Dropdown>
        </Field>
        <Field label={t('subruleset.version')} hint={t('subruleset.versionHint')}>
          <Dropdown
            placeholder={versions.data?.length === 0 ? t('subruleset.noVersions') : t('subruleset.chooseVersion')}
            value={String(node.version ?? '')}
            selectedOptions={node.version ? [String(node.version)] : []}
            onOptionSelect={(_, d) => set({ ...node, version: d.optionValue })}
          >
            {versions.data?.map((v) => (
              <Option key={v.version} value={v.version}>
                {v.version}
              </Option>
            ))}
          </Dropdown>
        </Field>
      </div>
      <Checkbox
        label={t('subruleset.forEach')}
        checked={forEach !== undefined}
        onChange={(_, d) => {
          const next: RgdNode = { ...node }
          if (d.checked) next.forEach = { ref: '' }
          else delete next.forEach
          set(next)
        }}
      />
      {forEach !== undefined && isRef(forEach) && (
        <div className="nested stack">
          <FieldPicker
            ariaLabel={t('subruleset.list')}
            placeholder={t('subruleset.chooseList')}
            value={forEach.ref}
            filter={(c) => Boolean(c.many) || c.types.includes('array') || c.types.length === 0}
            onChange={(ref) => set({ ...node, forEach: { ref } })}
          />
          <Field label={t('subruleset.passWhen')}>
            <Dropdown
              value={node.passWhen === 'any' ? t('subruleset.passAny') : t('subruleset.passAll')}
              selectedOptions={[String(node.passWhen ?? 'all')]}
              onOptionSelect={(_, d) => set({ ...node, passWhen: d.optionValue })}
            >
              <Option value="all">{t('subruleset.passAll')}</Option>
              <Option value="any">{t('subruleset.passAny')}</Option>
            </Dropdown>
          </Field>
        </div>
      )}
      <Checkbox
        label={forEach !== undefined ? t('subruleset.otherItemInput') : t('subruleset.otherInput')}
        checked={hasInput}
        onChange={(_, d) => {
          const next: RgdNode = { ...node }
          if (d.checked) next.input = { ref: forEach !== undefined ? '$.item' : '$.input' }
          else delete next.input
          set(next)
        }}
      />
      {hasInput && (
        <ScopeContext.Provider value={inner}>
          <ExpressionEditor value={node.input} onChange={(input) => set({ ...node, input })} />
        </ScopeContext.Provider>
      )}
      <Field label={t('subruleset.target')} hint={t('subruleset.targetHint')}>
        <Input
          value={String(node.target ?? '')}
          onChange={(_, d) => {
            const next: RgdNode = { ...node, target: d.value }
            if (!d.value) delete next.target
            if (!d.value || IDENT.test(d.value)) set(next)
          }}
        />
      </Field>
      <Text size={200} className="muted">
        {rich('subruleset.help', { fail: <b>fail</b> })}
      </Text>
    </div>
  )
}
