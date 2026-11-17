import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Option,
  Radio,
  RadioGroup,
  Spinner,
  Text,
  Textarea,
} from '@fluentui/react-components'
import { ArrowDownload16Regular, Delete16Regular } from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiError, errorMessage } from '../api/client'
import {
  addTest,
  deleteAliasEntry,
  deleteTest,
  downloadJson,
  exportBundle,
  fetchDiff,
  keys,
  publish,
  runTests,
  setAlias,
  simulateDraft,
  useRuleset,
  useSchemas,
  useTests,
  useVersions,
} from '../api/hooks'
import type { Change, ExecutionResult, GraphDiff, Issue, TestRun } from '../api/types'
import { ErrorBar, FormDialog, JsonField } from '../components/forms'
import { type Key, type Params, useI18n } from '../i18n'
import { exitReasonText, feedbackText, translateApiText } from '../i18n/api'
import { useEditor } from './store'

const OUTCOMES = new Set(['valid', 'invalid', 'warning', 'error'])

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const color = outcome === 'valid' ? 'success' : outcome === 'warning' ? 'warning' : 'danger'
  const { t } = useI18n()
  return (
    <Badge appearance="filled" color={color}>
      {OUTCOMES.has(outcome) ? t(`outcome.${outcome}` as Key) : outcome}
    </Badge>
  )
}

export function ResultView({ result }: { result: ExecutionResult }) {
  const { t } = useI18n()
  return (
    <div className="stack">
      <div className="inline">
        <OutcomeBadge outcome={result.outcome} />
        <Text size={200} className="muted">
          {t('result.exit', { node: result.exit.nodeId, reason: exitReasonText(result.exit.reason), us: result.timing.engineUs })}
        </Text>
      </div>
      {result.feedback.length === 0 && <Text size={200}>{t('result.noMessages')}</Text>}
      <ul className="feedback">
        {result.feedback.map((f, i) => (
          <li key={`${f.code}-${i}`} className={`sev-${f.severity}`}>
            <code>{f.code}</code> {feedbackText(f)}
            {f.data && <pre className="mini">{JSON.stringify(f.data)}</pre>}
          </li>
        ))}
      </ul>
      <Text weight="semibold">{t('result.output')}</Text>
      <pre>{JSON.stringify(result.result, null, 2)}</pre>
    </div>
  )
}

/** Saves the draft if needed; returns false when saving failed. */
export type EnsureSaved = () => Promise<boolean>

export function SimulatePanel({ ws, rs, ensureSaved }: { ws: string; rs: string; ensureSaved: EnsureSaved }) {
  const tests = useTests(ws, rs)
  const simulation = useEditor((s) => s.simulation)
  const simulated = useEditor((s) => s.simulated)
  const setSimulation = useEditor((s) => s.setSimulation)
  const graph = useEditor((s) => s.graph)
  // The form lives in the editor store: it survives switching to a node and back.
  const { input, referenceDate, locale } = useEditor((s) => s.simRequest)
  const setSimRequest = useEditor((s) => s.setSimRequest)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [testName, setTestName] = useState('')
  const qc = useQueryClient()
  const { t } = useI18n()

  async function run() {
    setBusy(true)
    setError(null)
    try {
      if (!(await ensureSaved())) return
      const options: Record<string, unknown> = { trace: 'full', locale }
      if (referenceDate) options.referenceDate = referenceDate
      setSimulation(await simulateDraft(ws, rs, input, options), { input, referenceDate, locale })
    } catch (e) {
      setError(e)
      setSimulation(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      {tests.data && tests.data.length > 0 && (
        <Field label={t('simulate.loadTest')}>
          <Dropdown
            placeholder={t('simulate.chooseTest')}
            onOptionSelect={(_, d) => {
              const test = tests.data?.find((x) => x.name === d.optionValue)
              if (test) setSimRequest({ input: test.input, referenceDate: test.referenceDate ?? '' })
            }}
          >
            {tests.data.map((test) => (
              <Option key={test.name} value={test.name}>
                {test.name}
              </Option>
            ))}
          </Dropdown>
        </Field>
      )}
      <JsonField label={t('simulate.input')} value={input} onValid={(v) => setSimRequest({ input: v })} rows={12} />
      <div className="inline">
        <Field label={t('simulate.referenceDate')}>
          <Input type="date" value={referenceDate} onChange={(_, d) => setSimRequest({ referenceDate: d.value })} />
        </Field>
        <Field label={t('common.language')}>
          <Dropdown value={locale} selectedOptions={[locale]} onOptionSelect={(_, d) => setSimRequest({ locale: d.optionValue ?? 'it' })}>
            <Option value="it">it</Option>
            <Option value="en">en</Option>
          </Dropdown>
        </Field>
      </div>
      <Button appearance="primary" onClick={run} disabled={busy}>
        {busy ? t('simulate.running') : t('simulate.run')}
      </Button>
      <ErrorBar error={error} />
      {error instanceof ApiError && Array.isArray(error.problem.issues) && (
        <IssueList issues={error.problem.issues as Issue[]} />
      )}
      {simulation && (
        <>
          <ResultView result={simulation} />
          <Text size={200}>{t('simulate.selectNode')}</Text>
          {simulated && simulated.graph !== graph && <Text size={200}>{t('simulate.staleResult')}</Text>}
          <FormDialog
            title={t('simulate.saveAsTestTitle')}
            submitLabel={t('common.save')}
            canSubmit={Boolean(testName.trim())}
            trigger={
              <Button disabled={!simulated || simulated.graph !== graph}>{t('simulate.saveAsTest')}</Button>
            }
            onSubmit={async () => {
              if (!simulated) return
              // What was actually simulated, not what the form holds now.
              await addTest(ws, rs, {
                name: testName.trim(),
                input: simulated.input,
                referenceDate: simulated.referenceDate || null,
                expected: {
                  outcome: simulation.outcome,
                  feedbackCodes: simulation.feedback.map((f) => f.code),
                  result: simulation.result,
                },
              })
              await qc.invalidateQueries({ queryKey: keys.tests(ws, rs) })
              setTestName('')
            }}
          >
            <Text>{t('simulate.saveAsTestHint')}</Text>
            <Field label={t('simulate.testName')} required>
              <Input value={testName} onChange={(_, d) => setTestName(d.value)} />
            </Field>
          </FormDialog>
        </>
      )}
    </div>
  )
}

export function TestsPanel({ ws, rs, ensureSaved }: { ws: string; rs: string; ensureSaved: EnsureSaved }) {
  const tests = useTests(ws, rs)
  const [run, setRun] = useState<TestRun | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const results = new Map(run?.tests.map((r) => [r.name, r]))
  const { t } = useI18n()

  return (
    <div className="stack">
      <Text size={200}>{t('tests.intro')}</Text>
      <Button
        appearance="primary"
        disabled={busy || !tests.data?.length}
        onClick={async () => {
          setBusy(true)
          setError(null)
          try {
            if (await ensureSaved()) setRun(await runTests(ws, rs))
          } catch (e) {
            setError(e)
          } finally {
            setBusy(false)
          }
        }}
      >
        {t('tests.run')}
      </Button>
      <ErrorBar error={error ?? tests.error} />
      {tests.isLoading && <Spinner size="tiny" />}
      {tests.data?.length === 0 && <Text>{t('tests.empty')}</Text>}
      <ul className="test-list">
        {tests.data?.map((test) => {
          const r = results.get(test.name)
          return (
            <li key={test.name}>
              <div className="inline">
                {r && <Badge color={r.passed ? 'success' : 'danger'}>{r.passed ? t('tests.passed') : t('tests.failed')}</Badge>}
                <Text weight="semibold">{test.name}</Text>
                <Text size={200} className="muted">
                  {t('tests.expected', { outcome: test.expected.outcome ?? '—' })}
                </Text>
                <Button
                  size="small"
                  appearance="subtle"
                  onClick={async () => {
                    await deleteTest(ws, rs, test.name)
                    await qc.invalidateQueries({ queryKey: keys.tests(ws, rs) })
                  }}
                >
                  {t('common.delete')}
                </Button>
              </div>
              {r && !r.passed && (
                <ul className="diffs">
                  {r.differences.map((d) => (
                    <li key={d}>{translateApiText(d)}</li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

const ENVS = ['dev', 'test', 'prod']

export function VersionsPanel({ ws, rs, ensureSaved }: { ws: string; rs: string; ensureSaved: EnsureSaved }) {
  const versions = useVersions(ws, rs)
  const qc = useQueryClient()
  const [bump, setBump] = useState<'major' | 'minor' | 'patch'>('minor')
  const [notes, setNotes] = useState('')
  const [promoteTo, setPromoteTo] = useState('')
  const [problem, setProblem] = useState<ApiError | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [aliasError, setAliasError] = useState<unknown>(null)
  const info = useRuleset(ws, rs)
  const aliases = info.data?.aliases ?? {}
  const schedule = info.data?.schedule ?? {}
  const { t, dateLocale } = useI18n()

  async function refresh() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: keys.versions(ws, rs) }),
      qc.invalidateQueries({ queryKey: keys.ruleset(ws, rs) }),
    ])
  }

  return (
    <div className="stack">
      <FormDialog
        title={t('versions.publishTitle')}
        submitLabel={t('versions.publish')}
        trigger={<Button appearance="primary">{t('versions.publishMenu')}</Button>}
        onSubmit={async () => {
          setProblem(null)
          if (!(await ensureSaved())) throw new Error(t('versions.saveFailed'))
          try {
            const v = await publish(ws, rs, { bump, notes: notes || undefined, promoteTo: promoteTo || undefined })
            setMessage(
              promoteTo
                ? t('versions.publishedPromoted', { version: v.version, env: promoteTo })
                : t('versions.published', { version: v.version }),
            )
            await refresh()
          } catch (e) {
            if (e instanceof ApiError) setProblem(e)
            throw e
          }
        }}
      >
        <Text>{t('versions.publishIntro')}</Text>
        <RadioGroup value={bump} onChange={(_, d) => setBump(d.value as typeof bump)} aria-label={t('versions.bump')}>
          <Radio value="patch" label={t('versions.patch')} />
          <Radio value="minor" label={t('versions.minor')} />
          <Radio value="major" label={t('versions.major')} />
        </RadioGroup>
        <Field label={t('versions.notes')}>
          <Textarea value={notes} onChange={(_, d) => setNotes(d.value)} />
        </Field>
        <Field label={t('versions.promoteTo')}>
          <Dropdown
            value={promoteTo || t('versions.noEnvironment')}
            selectedOptions={[promoteTo]}
            onOptionSelect={(_, d) => setPromoteTo(d.optionValue ?? '')}
          >
            <Option value="">{t('versions.noEnvironment')}</Option>
            {ENVS.map((e) => (
              <Option key={e} value={e}>
                {e}
              </Option>
            ))}
          </Dropdown>
        </Field>
        {problem && Array.isArray(problem.problem.issues) && <IssueList issues={problem.problem.issues as Issue[]} />}
        {problem && Array.isArray(problem.problem.tests) && (
          <ul className="diffs">
            {(problem.problem.tests as TestRun['tests']).filter((r) => !r.passed).map((r) => (
              <li key={r.name}>
                {r.name}: {r.differences.map((d) => translateApiText(d)).join('; ')}
              </li>
            ))}
          </ul>
        )}
      </FormDialog>
      {message && (
        <MessageBar intent="success">
          <MessageBarBody>{message}</MessageBarBody>
        </MessageBar>
      )}

      <Text weight="semibold">{t('versions.environments')}</Text>
      <Text size={200} className="muted">
        {t('versions.environmentsHint')}
      </Text>
      <table className="field-table" aria-label={t('versions.byEnvironment')}>
        <tbody>
          {ENVS.map((env) => (
            <tr key={env}>
              <td>
                <b>{env}</b>
              </td>
              <td>
                {(schedule[env] ?? []).length === 0 && <Text className="muted">—</Text>}
                <div className="stack-tight">
                  {(schedule[env] ?? []).map((entry) => (
                    <div key={entry.effectiveFrom ?? 'always'} className="inline">
                      <Badge appearance={aliases[env] === entry.version ? 'filled' : 'tint'}>{entry.version}</Badge>
                      <Text size={200}>
                        {entry.effectiveFrom
                          ? t('versions.since', { date: formatDay(entry.effectiveFrom, dateLocale) })
                          : t('versions.noStart')}
                      </Text>
                      <Button
                        size="small"
                        appearance="subtle"
                        aria-label={t('versions.removeFromEnv', { version: entry.version, env })}
                        icon={<Delete16Regular />}
                        onClick={async () => {
                          setAliasError(null)
                          try {
                            await deleteAliasEntry(ws, rs, env, entry.effectiveFrom)
                            await refresh()
                          } catch (e) {
                            setAliasError(e)
                          }
                        }}
                      />
                    </div>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ErrorBar error={aliasError} />

      <Text weight="semibold">{t('versions.list')}</Text>
      {versions.isLoading && <Spinner size="tiny" />}
      {versions.data?.length === 0 && <Text>{t('versions.empty')}</Text>}
      <ul className="version-list">
        {versions.data?.map((v) => (
          <li key={v.version}>
            <div className="inline">
              <Text weight="semibold">{v.version}</Text>
              <Text size={200} className="muted">
                {new Date(v.publishedAt).toLocaleString(dateLocale)} · {v.publishedBy}
              </Text>
            </div>
            {v.notes && <Text size={200}>{v.notes}</Text>}
            <div className="inline">
              <PromoteDialog ws={ws} rs={rs} version={v.version} onDone={refresh} />
              <DiffDialog ws={ws} rs={rs} from={v.version} />
              <Button
                size="small"
                appearance="subtle"
                icon={<ArrowDownload16Regular />}
                onClick={async () => downloadJson(`${rs}-${v.version}.minos.json`, await exportBundle(ws, rs, v.version))}
              >
                {t('common.export')}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function formatDay(iso: string, locale: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'long', year: 'numeric' })
}

function PromoteDialog({ ws, rs, version, onDone }: { ws: string; rs: string; version: string; onDone: () => Promise<void> }) {
  const [env, setEnv] = useState('prod')
  const [when, setWhen] = useState<'now' | 'date'>('now')
  const [day, setDay] = useState('')
  const { t } = useI18n()
  return (
    <FormDialog
      title={t('versions.promoteTitle', { version })}
      submitLabel={t('common.confirm')}
      canSubmit={when === 'now' || Boolean(day)}
      trigger={<Button size="small">{t('versions.promote')}</Button>}
      onSubmit={async () => {
        await setAlias(ws, rs, env, version, when === 'date' ? day : null)
        await onDone()
      }}
    >
      <Field label={t('versions.environment')}>
        <Dropdown value={env} selectedOptions={[env]} onOptionSelect={(_, d) => setEnv(d.optionValue ?? 'prod')}>
          {ENVS.map((e) => (
            <Option key={e} value={e}>
              {e}
            </Option>
          ))}
        </Dropdown>
      </Field>
      <RadioGroup value={when} onChange={(_, d) => setWhen(d.value as 'now' | 'date')} aria-label={t('versions.when')}>
        <Radio value="now" label={t('versions.now')} />
        <Radio value="date" label={t('versions.fromDate')} />
      </RadioGroup>
      {when === 'date' && (
        <Field label={t('versions.effectiveFrom')}>
          <Input type="date" value={day} onChange={(_, d) => setDay(d.value)} />
        </Field>
      )}
    </FormDialog>
  )
}

function changeText(c: Change, t: (key: Key, params?: Params) => string): string {
  const v = (x: unknown) => (x === undefined ? '' : JSON.stringify(x))
  if (c.kind === 'added') return t('diff.added', { path: c.path, value: v(c.to) })
  if (c.kind === 'removed') return t('diff.removed', { path: c.path, value: v(c.from) })
  return `${c.path}: ${v(c.from)} → ${v(c.to)}`
}

export function DiffDialog({ ws, rs, from }: { ws: string; rs: string; from: string }) {
  const [diff, setDiff] = useState<GraphDiff | null>(null)
  const [error, setError] = useState<unknown>(null)
  const { t } = useI18n()
  return (
    <Dialog
      onOpenChange={async (_, d) => {
        if (!d.open) return
        setDiff(null)
        setError(null)
        try {
          setDiff(await fetchDiff(ws, rs, from))
        } catch (e) {
          setError(e)
        }
      }}
    >
      <DialogTrigger disableButtonEnhancement>
        <Button size="small" appearance="subtle">
          {t('diff.compare')}
        </Button>
      </DialogTrigger>
      <DialogSurface className="wide-dialog">
        <DialogBody>
          <DialogTitle>{t('diff.title', { from })}</DialogTitle>
          <DialogContent className="stack">
            <ErrorBar error={error} />
            {!diff && !error && <Spinner size="tiny" />}
            {diff?.identical && <Text>{t('diff.identical')}</Text>}
            {diff && !diff.identical && (
              <>
                {diff.nodes.added.length > 0 && (
                  <section>
                    <Text weight="semibold">{t('diff.nodesAdded')}</Text>
                    <ul className="diff-list added">
                      {diff.nodes.added.map((n) => (
                        <li key={n.id}>
                          {n.label ?? n.id} <span className="muted">({n.type})</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {diff.nodes.removed.length > 0 && (
                  <section>
                    <Text weight="semibold">{t('diff.nodesRemoved')}</Text>
                    <ul className="diff-list removed">
                      {diff.nodes.removed.map((n) => (
                        <li key={n.id}>
                          {n.label ?? n.id} <span className="muted">({n.type})</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {diff.nodes.changed.map((n) => (
                  <section key={n.id}>
                    <Text weight="semibold">{t('diff.nodeChanged', { id: n.id })}</Text>
                    <ul className="diff-list">
                      {n.changes.map((c) => (
                        <li key={c.path}>
                          <code>{changeText(c, t)}</code>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
                {(diff.edges.added.length > 0 || diff.edges.removed.length > 0) && (
                  <section>
                    <Text weight="semibold">{t('diff.edges')}</Text>
                    <ul className="diff-list">
                      {diff.edges.added.map((e) => (
                        <li key={`+${e}`} className="added">
                          + {e}
                        </li>
                      ))}
                      {diff.edges.removed.map((e) => (
                        <li key={`-${e}`} className="removed">
                          − {e}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {diff.other.length > 0 && (
                  <section>
                    <Text weight="semibold">{t('diff.other')}</Text>
                    <ul className="diff-list">
                      {diff.other.map((c) => (
                        <li key={c.path}>
                          <code>{changeText(c, t)}</code>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </>
            )}
          </DialogContent>
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button>{t('common.close')}</Button>
            </DialogTrigger>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  )
}

export function SettingsPanel({ ws, entity }: { ws: string; entity: string | undefined }) {
  const graph = useEditor((s) => s.graph)
  const change = useEditor((s) => s.change)
  const schemaVersion = useEditor((s) => s.schemaVersion)
  const setSchemaVersion = useEditor((s) => s.setSchemaVersion)
  const schemas = useSchemas(ws, entity ?? '')
  const { t } = useI18n()
  if (!graph) return null
  const settings = graph.settings ?? {}
  return (
    <div className="stack">
      <Field label={t('settings.mode')} hint={t('settings.modeHint')}>
        <Dropdown
          value={settings.mode === 'collect_all' ? t('settings.collectAll') : t('settings.failFast')}
          selectedOptions={[settings.mode ?? 'fail_fast']}
          onOptionSelect={(_, d) =>
            change((g) => ({ ...g, settings: { ...g.settings, mode: d.optionValue as 'fail_fast' | 'collect_all' } }))
          }
        >
          <Option value="fail_fast">{t('settings.failFast')}</Option>
          <Option value="collect_all">{t('settings.collectAll')}</Option>
        </Dropdown>
      </Field>
      <Field label={t('settings.locale')}>
        <Dropdown
          value={settings.locale ?? 'it'}
          selectedOptions={[settings.locale ?? 'it']}
          onOptionSelect={(_, d) => change((g) => ({ ...g, settings: { ...g.settings, locale: d.optionValue } }))}
        >
          <Option value="it">it</Option>
          <Option value="en">en</Option>
        </Dropdown>
      </Field>
      {entity && (
        <Field label={t('settings.schemaVersion', { entity })}>
          <Dropdown
            value={schemaVersion ? `v${schemaVersion}` : t('settings.noSchema')}
            selectedOptions={[String(schemaVersion ?? '')]}
            onOptionSelect={(_, d) => setSchemaVersion(d.optionValue ? Number(d.optionValue) : null)}
          >
            {schemas.data?.map((s) => (
              <Option key={s.version} value={String(s.version)}>
                {`v${s.version}`}
              </Option>
            ))}
          </Dropdown>
        </Field>
      )}
      <JsonField
        label={t('settings.constants')}
        hint={t('settings.constantsHint')}
        value={graph.constants ?? {}}
        onValid={(constants) => change((g) => ({ ...g, constants: constants as Record<string, unknown> }))}
        rows={14}
      />
    </div>
  )
}

export function IssueList({ issues, onSelect }: { issues: Issue[]; onSelect?: (where: string) => void }) {
  useI18n() // re-render in the new language
  return (
    <ul className="issues">
      {issues.map((i, n) => (
        <li key={`${i.where}-${n}`}>
          {onSelect ? (
            <button type="button" className="link" onClick={() => onSelect(i.where)}>
              {i.where}
            </button>
          ) : (
            <code>{i.where}</code>
          )}{' '}
          {translateApiText(i.message)}
        </li>
      ))}
    </ul>
  )
}

export function NodeIO({ nodeId }: { nodeId: string }) {
  const simulation = useEditor((s) => s.simulation)
  const { t, rich } = useI18n()
  if (!simulation) return null
  const entry = simulation.trace?.find((x) => x.nodeId === nodeId)
  const feedback = simulation.feedback.filter((f) => f.nodeId === nodeId)
  return (
    <section className="panel-section io">
      <Text weight="semibold">{t('io.title')}</Text>
      {!entry ? (
        <Text size={200}>{t('io.notExecuted')}</Text>
      ) : (
        <>
          <Text size={200}>
            {rich('io.outcome', { outcome: <b>{entry.outcome}</b> })}
            {entry.port ? t('io.port', { port: entry.port }) : ''}
            {entry.us !== undefined ? ` · ${entry.us} µs` : ''}
          </Text>
          {entry.output !== undefined && entry.output !== null && <pre className="mini">{JSON.stringify(entry.output, null, 2)}</pre>}
          {feedback.map((f, i) => (
            <Text key={i} size={200}>
              <code>{f.code}</code> {feedbackText(f)}
            </Text>
          ))}
        </>
      )}
    </section>
  )
}

export function errorText(e: unknown): string {
  return errorMessage(e)
}
