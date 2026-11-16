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
        <Field label="Quale riga vale">
          <Dropdown
            value={hitPolicies.find((h) => h.key === hit)?.label.it ?? hit}
            selectedOptions={[hit]}
            onOptionSelect={(_, d) => set({ ...node, hitPolicy: d.optionValue })}
          >
            {hitPolicies.map((h) => (
              <Option key={h.key} value={h.key}>
                {h.label.it ?? h.key}
              </Option>
            ))}
          </Dropdown>
        </Field>
        <Field label="Salva il risultato in" hint={`Disponibile come $.vars.${String(node.target ?? '')}`}>
          <Input
            value={String(node.target ?? '')}
            onChange={(_, d) => IDENT.test(d.value) && set({ ...node, target: d.value })}
          />
        </Field>
      </div>

      <Text weight="semibold">Colonne di input</Text>
      {inputs.map((col, i) => (
        <div key={i} className="rule-card">
          <div className="inline">
            <Input
              aria-label={`Nome input ${i + 1}`}
              value={col.label ?? col.name}
              onChange={(_, d) => write({ inputs: inputs.map((c, j) => (j === i ? { ...c, label: d.value } : c)) })}
            />
            <Button size="small" appearance="subtle" onClick={() => setOpenInput(openInput === i ? null : i)}>
              {openInput === i ? 'Chiudi' : isBlank(col.expr) ? 'Scegli il valore' : describe(col.expr)}
            </Button>
            {inputs.length > 1 && (
              <Button
                size="small"
                appearance="subtle"
                aria-label={`Rimuovi input ${col.label ?? col.name}`}
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
            const name = uniqueName('input', inputs.map((c) => c.name))
            write({
              inputs: [...inputs, { name, label: name, expr: { ref: '' } }],
              rules: rules.map((r) => ({ ...r, when: [...r.when, null] })),
            })
            setOpenInput(inputs.length)
          }}
        >
          Input
        </Button>
        <Button
          size="small"
          icon={<Add16Regular />}
          onClick={() => {
            const name = uniqueName('risultato', outputs.map((c) => c.name))
            write({ outputs: [...outputs, { name, label: name }] })
          }}
        >
          Output
        </Button>
      </div>

      <div className="dt-scroll">
        <table className="dt" aria-label="Righe della tabella decisionale">
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
                    aria-label={`Nome output ${i + 1}`}
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
              {hit === 'priority' && <th>Priorità</th>}
              <th aria-label="Azioni" />
            </tr>
          </thead>
          <tbody>
            {rules.map((rule, i) => (
              <tr key={i}>
                <td className="dt-num">{i + 1}</td>
                {inputs.map((c, j) => (
                  <td key={`i-${c.name}`}>
                    <CellInput
                      label={`Riga ${i + 1}, ${c.label ?? c.name}`}
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
                      label={`Riga ${i + 1}, ${c.name}`}
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
                      label={`Priorità riga ${i + 1}`}
                      value={rule.priority ?? 0}
                      format={(v) => String(v)}
                      parse={(t) => Number(t) || 0}
                      onChange={(v) => setRule(i, { ...rule, priority: v as number })}
                    />
                  </td>
                )}
                <td className="dt-actions">
                  <Tooltip content="Su" relationship="label">
                    <Button size="small" appearance="subtle" icon={<ArrowUp16Regular />} disabled={i === 0} onClick={() => move(i, -1)} />
                  </Tooltip>
                  <Tooltip content="Giù" relationship="label">
                    <Button size="small" appearance="subtle" icon={<ArrowDown16Regular />} disabled={i === rules.length - 1} onClick={() => move(i, 1)} />
                  </Tooltip>
                  <Tooltip content={`Rimuovi riga ${i + 1}`} relationship="label">
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
        Riga
      </Button>
      <Text size={200} className="muted">
        Celle: vuoto = qualsiasi · <code>EMBA</code> · <code>A, B</code> (uno tra) · <code>&gt;= 60</code> ·{' '}
        <code>30..59</code> · <code>2027-01-01..2027-12-31</code> · <code>!= X</code> · <code>$.vars.nome</code>. Se nessuna
        riga vale, il nodo esce da <b>fail</b>.
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

  return (
    <div className="stack">
      <div className="inline">
        <Field label="Rule set da eseguire">
          <Dropdown
            placeholder="Scegli un rule set"
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
        <Field label="Versione" hint="Fissata: il risultato resta riproducibile">
          <Dropdown
            placeholder={versions.data?.length === 0 ? 'Nessuna versione pubblicata' : 'Scegli'}
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
        label="Esegui per ogni elemento di una lista"
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
            ariaLabel="Lista da percorrere"
            placeholder="Scegli una lista"
            value={forEach.ref}
            filter={(c) => Boolean(c.many) || c.types.includes('array') || c.types.length === 0}
            onChange={(ref) => set({ ...node, forEach: { ref } })}
          />
          <Field label="Il nodo passa se">
            <Dropdown
              value={node.passWhen === 'any' ? 'Almeno un elemento è valido' : 'Tutti gli elementi sono validi'}
              selectedOptions={[String(node.passWhen ?? 'all')]}
              onOptionSelect={(_, d) => set({ ...node, passWhen: d.optionValue })}
            >
              <Option value="all">Tutti gli elementi sono validi</Option>
              <Option value="any">Almeno un elemento è valido</Option>
            </Dropdown>
          </Field>
        </div>
      )}
      <Checkbox
        label={forEach !== undefined ? 'Passa un valore diverso dall’elemento' : 'Passa un valore diverso dall’oggetto in input'}
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
      <Field label="Salva il risultato in (facoltativo)" hint="Esito e output del rule set annidato, in $.vars">
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
        I messaggi del rule set annidato compaiono nel risultato con il suo nodo d’origine; il nodo esce da <b>fail</b> se
        il rule set non è valido.
      </Text>
    </div>
  )
}
