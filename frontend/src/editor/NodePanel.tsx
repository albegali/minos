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
import { type Key, useI18n } from '../i18n'
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
  const { t } = useI18n()
  const rename = (from: string, to: string) =>
    onChange(Object.fromEntries(entries.map(([k, v]) => [k === from ? to : k, v])))
  return (
    <div className="stack">
      {entries.map(([k, v]) => (
        <div key={k} className="kv-row">
          <div className="kv-head">
            <Field label={keyLabel}>
              <Input
                defaultValue={k}
                onBlur={(e) => {
                  const next = e.target.value.trim()
                  if (next && next !== k && !(next in value)) rename(k, next)
                }}
              />
            </Field>
            <Button
              appearance="subtle"
              aria-label={t('node.remove', { name: k })}
              icon={<Delete16Regular />}
              onClick={() => onChange(Object.fromEntries(entries.filter(([key]) => key !== k)))}
            />
          </div>
          <ExpressionEditor value={v} onChange={(x) => onChange({ ...value, [k]: x })} />
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
  const { t } = useI18n()
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
            <Field label={t('node.code')}>
              <Input value={value.code} onChange={(_, d) => onChange({ ...value, code: d.value })} />
            </Field>
            <Field label={t('node.severity')}>
              <Dropdown
                value={t(SEVERITY_LABEL[value.severity ?? 'error'])}
                selectedOptions={[value.severity ?? 'error']}
                onOptionSelect={(_, d) => onChange({ ...value, severity: d.optionValue as Severity })}
              >
                {(Object.keys(SEVERITY_LABEL) as Severity[]).map((s) => (
                  <Option key={s} value={s}>
                    {t(SEVERITY_LABEL[s])}
                  </Option>
                ))}
              </Dropdown>
            </Field>
          </div>
          {LOCALES.map((loc) => (
            <Field
              key={loc}
              label={t('node.messageIn', { locale: loc })}
              hint={loc === LOCALES[0] ? t('node.templateHint') : undefined}
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
          <Field label={t('node.affectedField')} hint={t('node.affectedFieldHint')}>
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
            {t('node.attachedData')}
          </Text>
          <KeyExprList
            value={value.data ?? {}}
            keyLabel={t('common.name')}
            addLabel={t('node.addData')}
            newKey={t('node.dataKey')}
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
  const { t } = useI18n()
  return (
    <>
      <FeedbackEditor title={t('node.failMessage')} value={value?.fail} onChange={(s) => set('fail', s)} />
      <FeedbackEditor title={t('node.passMessage')} value={value?.pass} onChange={(s) => set('pass', s)} />
    </>
  )
}

const SEVERITY_LABEL: Record<Severity, Key> = {
  info: 'node.severityInfo',
  warning: 'node.severityWarning',
  error: 'node.severityError',
}

type GroupOperator = NonNullable<RgdNode['operator']>

const GROUP_OPERATOR: Record<GroupOperator, Key> = { and: 'node.opAnd', or: 'node.opOr', not: 'node.opNot' }

const ON_FAIL: Record<string, Key> = {
  '': 'node.onFailDefault',
  stop: 'node.onFailStop',
  continue: 'node.onFailContinue',
  branch: 'node.onFailBranch',
}

function OnFail({ node, set }: { node: RgdNode; set: (n: RgdNode) => void }) {
  const current = (node.onFail as string | undefined) ?? ''
  const { t } = useI18n()
  return (
    <Field label={t('node.onFail')} hint={t('node.onFailHint')}>
      <Dropdown
        value={ON_FAIL[current] ? t(ON_FAIL[current]) : current}
        selectedOptions={[current]}
        onOptionSelect={(_, d) => {
          const next = { ...node, onFail: d.optionValue || undefined }
          if (!d.optionValue) delete next.onFail
          set(next)
        }}
      >
        {Object.entries(ON_FAIL).map(([k, label]) => (
          <Option key={k} value={k}>
            {t(label)}
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
  const { t } = useI18n()
  const write = (next: GroupChild[]) =>
    set({ ...node, children: next.map((c) => (c.feedback ? c : { rule: c.rule })) })
  return (
    <div className="stack">
      {children.map((child, i) => (
        <div key={i} className="rule-card">
          <div className="rule-card-head">
            <Button appearance="transparent" onClick={() => setOpen(open === i ? null : i)}>
              {t('node.rule', { n: i + 1, text: describe(child.rule) })}
            </Button>
            {children.length > 1 && (
              <Button
                appearance="subtle"
                aria-label={t('node.removeRule', { n: i + 1 })}
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
        {t('node.addRule')}
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
  const { t } = useI18n()
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
          <div className="kv-head">
            <Field label={t('node.branchName')}>
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
              aria-label={t('node.removeBranch', { name: c.name })}
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
          const base = t('graph.caseName')
          let name = `${base}${cases.length + 1}`
          for (let i = cases.length + 2; cases.some((x) => x.name === name); i++) name = `${base}${i}`
          write([...cases, { name, when: blankComparison() }])
        }}
      >
        {t('node.addBranch')}
      </Button>
      <Text size={200}>{t('node.switchHint')}</Text>
    </div>
  )
}

export function NodePanel({ node, manifest }: { node: RgdNode; manifest?: NodeManifest }) {
  const change = useEditor((s) => s.change)
  const select = useEditor((s) => s.select)
  const set = (next: RgdNode) => change((g) => updateNode(g, node.id, next))
  const { t, loc } = useI18n()

  return (
    <div className="stack node-panel">
      <div className="panel-title">
        <Text size={500} weight="semibold">
          {manifest ? loc(manifest.label) : node.type}
        </Text>
        <Text size={200} className="muted">
          {loc(manifest?.description)}
        </Text>
      </div>
      <div className="inline">
        <Field label={t('node.id')}>
          <Input value={node.id} readOnly />
        </Field>
        <Field label={t('node.label')}>
          <Input value={node.label ?? ''} onChange={(_, d) => set({ ...node, label: d.value })} />
        </Field>
      </div>

      {node.type === 'start' && <Text>{t('node.startHint')}</Text>}

      {node.type === 'condition' && (
        <>
          <Section title={t('node.condition')}>
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
            <Field label={t('node.combination')}>
              <Dropdown
                value={t(GROUP_OPERATOR[node.operator ?? 'and'])}
                selectedOptions={[node.operator ?? 'and']}
                onOptionSelect={(_, d) => set({ ...node, operator: d.optionValue as RgdNode['operator'] })}
              >
                {(Object.keys(GROUP_OPERATOR) as GroupOperator[]).map((op) => (
                  <Option key={op} value={op}>
                    {t(GROUP_OPERATOR[op])}
                  </Option>
                ))}
              </Dropdown>
            </Field>
            <Field label={t('node.evaluation')}>
              <Dropdown
                value={node.evaluate === 'all' ? t('node.evaluateAll') : t('node.evaluateShortCircuit')}
                selectedOptions={[(node.evaluate as string | undefined) ?? 'short_circuit']}
                onOptionSelect={(_, d) => set({ ...node, evaluate: d.optionValue })}
              >
                <Option value="all">{t('node.evaluateAll')}</Option>
                <Option value="short_circuit">{t('node.evaluateShortCircuit')}</Option>
              </Dropdown>
            </Field>
          </div>
          <Section title={t('node.rules')}>
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
        <Section title={t('node.computed')}>
          <KeyExprList
            value={(node.assign as Record<string, Expr> | undefined) ?? {}}
            keyLabel={t('node.variable')}
            addLabel={t('node.variable')}
            newKey={t('node.variableKey')}
            onChange={(assign) => set({ ...node, assign })}
          />
          <Text size={200}>{t('node.varsHint')}</Text>
        </Section>
      )}

      {node.type === 'switch' && (
        <Section title={t('node.branches')}>
          <SwitchCases node={node} />
        </Section>
      )}

      {node.type === 'feedback' && (
        <>
          <FeedbackEditor
            title={t('node.message')}
            value={node.feedback as FeedbackSpec | undefined}
            onChange={(feedback) => feedback && set({ ...node, feedback })}
          />
          <Checkbox
            label={t('node.onlyWhen')}
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
          <Field label={t('node.outcome')} hint={t('node.outcomeHint')}>
            <Dropdown
              value={t(`outcome.${node.outcome ?? 'valid'}`)}
              selectedOptions={[node.outcome ?? 'valid']}
              onOptionSelect={(_, d) => set({ ...node, outcome: d.optionValue as RgdNode['outcome'] })}
            >
              {(['valid', 'invalid', 'warning'] as const).map((o) => (
                <Option key={o} value={o}>
                  {t(`outcome.${o}`)}
                </Option>
              ))}
            </Dropdown>
          </Field>
          <Section title={t('node.output')}>
            <KeyExprList
              value={(node.output as Record<string, Expr> | undefined) ?? {}}
              keyLabel={t('common.key')}
              addLabel={t('node.addOutput')}
              newKey={t('node.outputKey')}
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
          {t('node.delete')}
        </Button>
      )}
    </div>
  )
}
