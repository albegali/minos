import {
  Button,
  Checkbox,
  Divider,
  Dropdown,
  Field,
  Input,
  Option,
  Text,
  Textarea,
} from '@fluentui/react-components'
import { Add16Regular, Delete16Regular } from '@fluentui/react-icons'
import { type ReactNode, useState } from 'react'

import type { NodeManifest } from '../api/types'
import type { RgdNode } from '../rgd'
import { ConditionBuilder } from './ConditionBuilder'
import { blankComparison, describe, type Expr } from './expr'
import { ExpressionEditor } from './ExpressionEditor'
import { pruneEdges, removeNode, renamePort, updateNode } from './graph'
import { DecisionTableEditor, SubRulesetEditor } from './nodeEditors'
import { omit } from '../util'
import { useEditor } from './store'

type Severity = 'info' | 'warning' | 'error'

export interface FeedbackSpec {
  code: string
  severity?: Severity
  message: string | Record<string, string>
  path?: string
  data?: Record<string, Expr>
}

const LOCALES = ['it', 'en'] as const

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel-section">
      <Text weight="semibold">{title}</Text>
      {children}
    </section>
  )
}

/** Editable list of `name → expression` pairs (set assignments, end output, feedback data). */
export function KeyExprList({
  value,
  onChange,
  keyLabel,
  addLabel,
  newKey,
}: {
  value: Record<string, Expr>
  onChange: (next: Record<string, Expr>) => void
  keyLabel: string
  addLabel: string
  newKey: string
}) {
  const entries = Object.entries(value)
  const rename = (from: string, to: string) =>
    onChange(Object.fromEntries(entries.map(([k, v]) => [k === from ? to : k, v])))
  return (
    <div className="stack">
      {entries.map(([k, v]) => (
        <div key={k} className="kv-row">
          <Field label={keyLabel}>
            <Input
              defaultValue={k}
              onBlur={(e) => {
                const next = e.target.value.trim()
                if (next && next !== k && !(next in value)) rename(k, next)
              }}
            />
          </Field>
          <ExpressionEditor value={v} onChange={(x) => onChange({ ...value, [k]: x })} />
          <Button
            appearance="subtle"
            aria-label={`Rimuovi ${k}`}
            icon={<Delete16Regular />}
            onClick={() => onChange(Object.fromEntries(entries.filter(([key]) => key !== k)))}
          />
        </div>
      ))}
      <Button
        size="small"
        icon={<Add16Regular />}
        onClick={() => {
          let name = newKey
          for (let i = 2; name in value; i++) name = `${newKey}${i}`
          onChange({ ...value, [name]: 0 })
        }}
      >
        {addLabel}
      </Button>
    </div>
  )
}

export function FeedbackEditor({
  value,
  onChange,
  title,
}: {
  value: FeedbackSpec | null | undefined
  onChange: (next: FeedbackSpec | null) => void
  title: string
}) {
  const enabled = Boolean(value)
  const messages: Record<string, string> =
    typeof value?.message === 'string' ? { it: value.message } : (value?.message ?? {})
  return (
    <div className="feedback-editor">
      <Checkbox
        label={title}
        checked={enabled}
        onChange={(_, d) =>
          onChange(d.checked ? { code: 'CODICE', severity: 'error', message: { it: '' } } : null)
        }
      />
      {value && (
        <div className="stack nested">
          <div className="inline">
            <Field label="Codice">
              <Input value={value.code} onChange={(_, d) => onChange({ ...value, code: d.value })} />
            </Field>
            <Field label="Gravità">
              <Dropdown
                value={{ info: 'Informazione', warning: 'Avviso', error: 'Errore' }[value.severity ?? 'error']}
                selectedOptions={[value.severity ?? 'error']}
                onOptionSelect={(_, d) => onChange({ ...value, severity: d.optionValue as Severity })}
              >
                <Option value="info">Informazione</Option>
                <Option value="warning">Avviso</Option>
                <Option value="error">Errore</Option>
              </Dropdown>
            </Field>
          </div>
          {LOCALES.map((loc) => (
            <Field
              key={loc}
              label={`Messaggio (${loc})`}
              hint={loc === 'it' ? 'Inserisci valori con {{vars.nome}} o {{input.campo}}' : undefined}
            >
              <Textarea
                rows={2}
                value={messages[loc] ?? ''}
                onChange={(_, d) => {
                  const next = d.value ? { ...messages, [loc]: d.value } : omit(messages, loc)
                  onChange({ ...value, message: next })
                }}
              />
            </Field>
          ))}
          <Field label="Campo interessato" hint="Per i form dei sistemi chiamanti, es. courses">
            <Input
              value={value.path ?? ''}
              onChange={(_, d) => {
                const next: FeedbackSpec = { ...value, path: d.value }
                if (!d.value) delete next.path
                onChange(next)
              }}
            />
          </Field>
          <Text size={200} weight="semibold">
            Dati allegati
          </Text>
          <KeyExprList
            value={value.data ?? {}}
            keyLabel="Nome"
            addLabel="Dato"
            newKey="valore"
            onChange={(data) => {
              const next: FeedbackSpec = { ...value, data }
              if (Object.keys(data).length === 0) delete next.data
              onChange(next)
            }}
          />
        </div>
      )}
    </div>
  )
}

interface PairValue {
  pass?: FeedbackSpec | null
  fail?: FeedbackSpec | null
}

function FeedbackPair({ value, onChange }: { value: PairValue | undefined; onChange: (v: PairValue | undefined) => void }) {
  const set = (key: 'pass' | 'fail', spec: FeedbackSpec | null) => {
    const next: PairValue = spec ? { ...value, [key]: spec } : omit({ ...value }, key)
    onChange(Object.keys(next).length > 0 ? next : undefined)
  }
  return (
    <>
      <FeedbackEditor title="Messaggio se fallisce" value={value?.fail} onChange={(s) => set('fail', s)} />
      <FeedbackEditor title="Messaggio se passa" value={value?.pass} onChange={(s) => set('pass', s)} />
    </>
  )
}

const ON_FAIL: Record<string, string> = {
  '': 'Predefinito (secondo la modalità)',
  stop: 'Interrompi subito (invalid)',
  continue: 'Registra e continua',
  branch: 'Segui il ramo "fail"',
}

function OnFail({ node, set }: { node: RgdNode; set: (n: RgdNode) => void }) {
  const current = (node.onFail as string | undefined) ?? ''
  return (
    <Field label="Se fallisce" hint="Il ramo fail, se collegato, viene sempre seguito">
      <Dropdown
        value={ON_FAIL[current]}
        selectedOptions={[current]}
        onOptionSelect={(_, d) => {
          const next = { ...node, onFail: d.optionValue || undefined }
          if (!d.optionValue) delete next.onFail
          set(next)
        }}
      >
        {Object.entries(ON_FAIL).map(([k, label]) => (
          <Option key={k} value={k}>
            {label}
          </Option>
        ))}
      </Dropdown>
    </Field>
  )
}

interface GroupChild {
  rule: Expr
  feedback?: PairValue
}

function asChild(c: unknown): GroupChild {
  return c && typeof c === 'object' && 'rule' in c ? (c as GroupChild) : { rule: c }
}

function GroupChildren({ node, set }: { node: RgdNode; set: (n: RgdNode) => void }) {
  const children = ((node.children as unknown[] | undefined) ?? []).map(asChild)
  const [open, setOpen] = useState<number | null>(0)
  const write = (next: GroupChild[]) =>
    set({ ...node, children: next.map((c) => (c.feedback ? c : { rule: c.rule })) })
  return (
    <div className="stack">
      {children.map((child, i) => (
        <div key={i} className="rule-card">
          <div className="rule-card-head">
            <Button appearance="transparent" onClick={() => setOpen(open === i ? null : i)}>
              Regola {i + 1}: {describe(child.rule)}
            </Button>
            {children.length > 1 && (
              <Button
                appearance="subtle"
                aria-label={`Rimuovi regola ${i + 1}`}
                icon={<Delete16Regular />}
                onClick={() => write(children.filter((_, j) => j !== i))}
              />
            )}
          </div>
          {open === i && (
            <div className="stack">
              <ConditionBuilder
                root
                value={child.rule}
                onChange={(rule) => write(children.map((c, j) => (j === i ? { ...c, rule } : c)))}
              />
              <FeedbackPair
                value={child.feedback}
                onChange={(feedback) => write(children.map((c, j) => (j === i ? { rule: c.rule, feedback } : c)))}
              />
            </div>
          )}
        </div>
      ))}
      <Button
        size="small"
        icon={<Add16Regular />}
        onClick={() => {
          write([...children, { rule: blankComparison() }])
          setOpen(children.length)
        }}
      >
        Regola
      </Button>
    </div>
  )
}

interface SwitchCase {
  name: string
  when: Expr
}

function SwitchCases({ node }: { node: RgdNode }) {
  const change = useEditor((s) => s.change)
  const cases = (node.cases as SwitchCase[] | undefined) ?? []
  const write = (next: SwitchCase[], rename?: [string, string]) =>
    change((g) => {
      let out = updateNode(g, node.id, { ...node, cases: next })
      if (rename) out = renamePort(out, node.id, rename[0], rename[1])
      return pruneEdges(out)
    })
  return (
    <div className="stack">
      {cases.map((c, i) => (
        <div key={c.name} className="rule-card">
          <div className="inline">
            <Field label="Nome del ramo">
              <Input
                defaultValue={c.name}
                onBlur={(e) => {
                  const to = e.target.value.trim()
                  if (to && to !== c.name && /^[A-Za-z_][A-Za-z0-9_-]*$/.test(to) && !cases.some((x) => x.name === to)) {
                    write(cases.map((x, j) => (j === i ? { ...x, name: to } : x)), [c.name, to])
                  }
                }}
              />
            </Field>
            <Button
              appearance="subtle"
              aria-label={`Rimuovi ramo ${c.name}`}
              icon={<Delete16Regular />}
              onClick={() => write(cases.filter((_, j) => j !== i))}
            />
          </div>
          <ConditionBuilder root value={c.when} onChange={(when) => write(cases.map((x, j) => (j === i ? { ...x, when } : x)))} />
        </div>
      ))}
      <Button
        size="small"
        icon={<Add16Regular />}
        onClick={() => {
          let name = `caso${cases.length + 1}`
          for (let i = cases.length + 2; cases.some((x) => x.name === name); i++) name = `caso${i}`
          write([...cases, { name, when: blankComparison() }])
        }}
      >
        Ramo
      </Button>
      <Text size={200}>Il primo ramo vero vince; se nessuno è vero si segue "default".</Text>
    </div>
  )
}

export function NodePanel({ node, manifest }: { node: RgdNode; manifest?: NodeManifest }) {
  const change = useEditor((s) => s.change)
  const select = useEditor((s) => s.select)
  const set = (next: RgdNode) => change((g) => updateNode(g, node.id, next))

  return (
    <div className="stack node-panel">
      <div className="panel-title">
        <Text size={500} weight="semibold">
          {manifest?.label.it ?? node.type}
        </Text>
        <Text size={200} className="muted">
          {manifest?.description.it}
        </Text>
      </div>
      <div className="inline">
        <Field label="Identificativo">
          <Input value={node.id} readOnly />
        </Field>
        <Field label="Etichetta">
          <Input value={node.label ?? ''} onChange={(_, d) => set({ ...node, label: d.value })} />
        </Field>
      </div>

      {node.type === 'start' && <Text>Il punto di ingresso: collega la sua uscita al primo controllo.</Text>}

      {node.type === 'condition' && (
        <>
          <Section title="Condizione">
            <ConditionBuilder root value={node.condition} onChange={(condition) => set({ ...node, condition })} />
          </Section>
          <OnFail node={node} set={set} />
          <Divider />
          <FeedbackPair
            value={node.feedback as PairValue | undefined}
            onChange={(feedback) => {
              const next = { ...node, feedback }
              if (!feedback) delete next.feedback
              set(next)
            }}
          />
        </>
      )}

      {node.type === 'group' && (
        <>
          <div className="inline">
            <Field label="Combinazione">
              <Dropdown
                value={{ and: 'Tutte vere (AND)', or: 'Almeno una (OR)', not: 'Non tutte (NOT)' }[node.operator ?? 'and']}
                selectedOptions={[node.operator ?? 'and']}
                onOptionSelect={(_, d) => set({ ...node, operator: d.optionValue as RgdNode['operator'] })}
              >
                <Option value="and">Tutte vere (AND)</Option>
                <Option value="or">Almeno una (OR)</Option>
                <Option value="not">Non tutte (NOT)</Option>
              </Dropdown>
            </Field>
            <Field label="Valutazione">
              <Dropdown
                value={node.evaluate === 'all' ? 'Tutte le regole' : 'Fino al primo esito decisivo'}
                selectedOptions={[(node.evaluate as string | undefined) ?? 'short_circuit']}
                onOptionSelect={(_, d) => set({ ...node, evaluate: d.optionValue })}
              >
                <Option value="all">Tutte le regole</Option>
                <Option value="short_circuit">Fino al primo esito decisivo</Option>
              </Dropdown>
            </Field>
          </div>
          <Section title="Regole">
            <GroupChildren node={node} set={set} />
          </Section>
          <OnFail node={node} set={set} />
          <Divider />
          <FeedbackPair
            value={node.feedback as PairValue | undefined}
            onChange={(feedback) => {
              const next = { ...node, feedback }
              if (!feedback) delete next.feedback
              set(next)
            }}
          />
        </>
      )}

      {node.type === 'decision_table' && (
        <>
          <DecisionTableEditor node={node} set={set} />
          <OnFail node={node} set={set} />
          <Divider />
          <FeedbackPair
            value={node.feedback as PairValue | undefined}
            onChange={(feedback) => {
              const next: RgdNode = { ...node, feedback }
              if (!feedback) delete next.feedback
              set(next)
            }}
          />
        </>
      )}

      {node.type === 'subruleset' && (
        <>
          <SubRulesetEditor node={node} set={set} />
          <OnFail node={node} set={set} />
          <Divider />
          <FeedbackPair
            value={node.feedback as PairValue | undefined}
            onChange={(feedback) => {
              const next: RgdNode = { ...node, feedback }
              if (!feedback) delete next.feedback
              set(next)
            }}
          />
        </>
      )}

      {node.type === 'set' && (
        <Section title="Variabili calcolate">
          <KeyExprList
            value={(node.assign as Record<string, Expr> | undefined) ?? {}}
            keyLabel="Variabile"
            addLabel="Variabile"
            newKey="variabile"
            onChange={(assign) => set({ ...node, assign })}
          />
          <Text size={200}>Disponibili negli altri nodi come $.vars.nome.</Text>
        </Section>
      )}

      {node.type === 'switch' && (
        <Section title="Rami">
          <SwitchCases node={node} />
        </Section>
      )}

      {node.type === 'feedback' && (
        <>
          <FeedbackEditor
            title="Messaggio"
            value={node.feedback as FeedbackSpec | undefined}
            onChange={(feedback) => feedback && set({ ...node, feedback })}
          />
          <Checkbox
            label="Solo se una condizione è vera"
            checked={node.when !== undefined}
            onChange={(_, d) => {
              const next = { ...node, when: d.checked ? blankComparison() : undefined }
              if (!d.checked) delete next.when
              set(next)
            }}
          />
          {node.when !== undefined && (
            <ConditionBuilder root value={node.when} onChange={(when) => set({ ...node, when })} />
          )}
        </>
      )}

      {node.type === 'end' && (
        <>
          <Field label="Esito" hint="Un esito valido diventa non valido se sono stati emessi errori">
            <Dropdown
              value={{ valid: 'Valido', invalid: 'Non valido', warning: 'Valido con avvisi' }[node.outcome ?? 'valid']}
              selectedOptions={[node.outcome ?? 'valid']}
              onOptionSelect={(_, d) => set({ ...node, outcome: d.optionValue as RgdNode['outcome'] })}
            >
              <Option value="valid">Valido</Option>
              <Option value="invalid">Non valido</Option>
              <Option value="warning">Valido con avvisi</Option>
            </Dropdown>
          </Field>
          <Section title="Output restituito">
            <KeyExprList
              value={(node.output as Record<string, Expr> | undefined) ?? {}}
              keyLabel="Chiave"
              addLabel="Valore in output"
              newKey="valore"
              onChange={(output) => {
                const next: RgdNode = { ...node, output }
                if (Object.keys(output).length === 0) delete next.output
                set(next)
              }}
            />
          </Section>
        </>
      )}

      {node.type !== 'start' && (
        <Button
          appearance="subtle"
          icon={<Delete16Regular />}
          onClick={() => {
            change((g) => removeNode(g, node.id))
            select(null)
          }}
        >
          Elimina nodo
        </Button>
      )}
    </div>
  )
}
