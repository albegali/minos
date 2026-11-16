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
import { useEditor } from './store'

const OUTCOME_LABEL: Record<string, string> = {
  valid: 'Valido',
  invalid: 'Non valido',
  warning: 'Valido con avvisi',
  error: 'Errore',
}

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const color = outcome === 'valid' ? 'success' : outcome === 'warning' ? 'warning' : 'danger'
  return (
    <Badge appearance="filled" color={color}>
      {OUTCOME_LABEL[outcome] ?? outcome}
    </Badge>
  )
}

export function ResultView({ result }: { result: ExecutionResult }) {
  return (
    <div className="stack">
      <div className="inline">
        <OutcomeBadge outcome={result.outcome} />
        <Text size={200} className="muted">
          uscita da {result.exit.nodeId} ({result.exit.reason}) · {result.timing.engineUs} µs
        </Text>
      </div>
      {result.feedback.length === 0 && <Text size={200}>Nessun messaggio.</Text>}
      <ul className="feedback">
        {result.feedback.map((f, i) => (
          <li key={`${f.code}-${i}`} className={`sev-${f.severity}`}>
            <code>{f.code}</code> {f.message}
            {f.data && <pre className="mini">{JSON.stringify(f.data)}</pre>}
          </li>
        ))}
      </ul>
      <Text weight="semibold">Output</Text>
      <pre>{JSON.stringify(result.result, null, 2)}</pre>
    </div>
  )
}

/** Saves the draft if needed; returns false when saving failed. */
export type EnsureSaved = () => Promise<boolean>

export function SimulatePanel({ ws, rs, ensureSaved }: { ws: string; rs: string; ensureSaved: EnsureSaved }) {
  const tests = useTests(ws, rs)
  const simulation = useEditor((s) => s.simulation)
  const setSimulation = useEditor((s) => s.setSimulation)
  const [input, setInput] = useState<unknown>({})
  const [referenceDate, setReferenceDate] = useState('')
  const [locale, setLocale] = useState('it')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [testName, setTestName] = useState('')
  const qc = useQueryClient()

  async function run() {
    setBusy(true)
    setError(null)
    try {
      if (!(await ensureSaved())) return
      const options: Record<string, unknown> = { trace: 'full', locale }
      if (referenceDate) options.referenceDate = referenceDate
      setSimulation(await simulateDraft(ws, rs, input, options))
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
        <Field label="Carica l'input di un test">
          <Dropdown
            placeholder="Scegli un test"
            onOptionSelect={(_, d) => {
              const t = tests.data?.find((x) => x.name === d.optionValue)
              if (t) {
                setInput(t.input)
                setReferenceDate(t.referenceDate ?? '')
              }
            }}
          >
            {tests.data.map((t) => (
              <Option key={t.name} value={t.name}>
                {t.name}
              </Option>
            ))}
          </Dropdown>
        </Field>
      )}
      <JsonField label="Oggetto in input" value={input} onValid={setInput} rows={12} />
      <div className="inline">
        <Field label="Data di riferimento">
          <Input type="date" value={referenceDate} onChange={(_, d) => setReferenceDate(d.value)} />
        </Field>
        <Field label="Lingua">
          <Dropdown value={locale} selectedOptions={[locale]} onOptionSelect={(_, d) => setLocale(d.optionValue ?? 'it')}>
            <Option value="it">it</Option>
            <Option value="en">en</Option>
          </Dropdown>
        </Field>
      </div>
      <Button appearance="primary" onClick={run} disabled={busy}>
        {busy ? 'Esecuzione…' : 'Simula il draft'}
      </Button>
      <ErrorBar error={error} />
      {error instanceof ApiError && Array.isArray(error.problem.issues) && (
        <IssueList issues={error.problem.issues as Issue[]} />
      )}
      {simulation && (
        <>
          <ResultView result={simulation} />
          <Text size={200}>Seleziona un nodo per vederne ingresso e uscita.</Text>
          <FormDialog
            title="Salva come test"
            submitLabel="Salva"
            canSubmit={Boolean(testName.trim())}
            trigger={<Button>Salva questa simulazione come test</Button>}
            onSubmit={async () => {
              await addTest(ws, rs, {
                name: testName.trim(),
                input,
                referenceDate: referenceDate || null,
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
            <Text>L'esito, i codici dei messaggi e l'output attuali diventano il risultato atteso.</Text>
            <Field label="Nome del test" required>
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
  const results = new Map(run?.tests.map((t) => [t.name, t]))

  return (
    <div className="stack">
      <Text size={200}>I test vengono eseguiti a ogni pubblicazione: se uno fallisce, la versione non viene creata.</Text>
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
        Esegui i test sul draft
      </Button>
      <ErrorBar error={error ?? tests.error} />
      {tests.isLoading && <Spinner size="tiny" />}
      {tests.data?.length === 0 && <Text>Nessun test. Salva una simulazione come test dalla scheda Simulazione.</Text>}
      <ul className="test-list">
        {tests.data?.map((t) => {
          const r = results.get(t.name)
          return (
            <li key={t.name}>
              <div className="inline">
                {r && <Badge color={r.passed ? 'success' : 'danger'}>{r.passed ? 'ok' : 'fallito'}</Badge>}
                <Text weight="semibold">{t.name}</Text>
                <Text size={200} className="muted">
                  atteso: {t.expected.outcome ?? '—'}
                </Text>
                <Button
                  size="small"
                  appearance="subtle"
                  onClick={async () => {
                    await deleteTest(ws, rs, t.name)
                    await qc.invalidateQueries({ queryKey: keys.tests(ws, rs) })
                  }}
                >
                  Elimina
                </Button>
              </div>
              {r && !r.passed && (
                <ul className="diffs">
                  {r.differences.map((d) => (
                    <li key={d}>{d}</li>
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

  async function refresh() {
    await Promise.all([
      qc.invalidateQueries({ queryKey: keys.versions(ws, rs) }),
      qc.invalidateQueries({ queryKey: keys.ruleset(ws, rs) }),
    ])
  }

  return (
    <div className="stack">
      <FormDialog
        title="Pubblica una nuova versione"
        submitLabel="Pubblica"
        trigger={<Button appearance="primary">Pubblica…</Button>}
        onSubmit={async () => {
          setProblem(null)
          if (!(await ensureSaved())) throw new Error('Salvataggio non riuscito')
          try {
            const v = await publish(ws, rs, { bump, notes: notes || undefined, promoteTo: promoteTo || undefined })
            setMessage(`Pubblicata la versione ${v.version}${promoteTo ? ` e promossa in ${promoteTo}` : ''}.`)
            await refresh()
          } catch (e) {
            if (e instanceof ApiError) setProblem(e)
            throw e
          }
        }}
      >
        <Text>Il draft viene compilato, controllato sullo schema e verificato con tutti i test.</Text>
        <RadioGroup value={bump} onChange={(_, d) => setBump(d.value as typeof bump)} aria-label="Tipo di versione">
          <Radio value="patch" label="Correzione (patch)" />
          <Radio value="minor" label="Modifica compatibile (minor)" />
          <Radio value="major" label="Modifica importante (major)" />
        </RadioGroup>
        <Field label="Note">
          <Textarea value={notes} onChange={(_, d) => setNotes(d.value)} />
        </Field>
        <Field label="Promuovi subito in">
          <Dropdown
            value={promoteTo || 'Nessun ambiente'}
            selectedOptions={[promoteTo]}
            onOptionSelect={(_, d) => setPromoteTo(d.optionValue ?? '')}
          >
            <Option value="">Nessun ambiente</Option>
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
            {(problem.problem.tests as TestRun['tests']).filter((t) => !t.passed).map((t) => (
              <li key={t.name}>
                {t.name}: {t.differences.join('; ')}
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

      <Text weight="semibold">Ambienti</Text>
      <Text size={200} className="muted">
        Ogni chiamata usa la versione in vigore alla sua data di riferimento: si possono pianificare le regole di un
        periodo (es. dal 1° agosto) mentre le attuali restano attive.
      </Text>
      <table className="field-table" aria-label="Versioni per ambiente">
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
                        {entry.effectiveFrom ? `dal ${formatDay(entry.effectiveFrom)}` : 'senza data di inizio'}
                      </Text>
                      <Button
                        size="small"
                        appearance="subtle"
                        aria-label={`Togli ${entry.version} da ${env}`}
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

      <Text weight="semibold">Versioni pubblicate</Text>
      {versions.isLoading && <Spinner size="tiny" />}
      {versions.data?.length === 0 && <Text>Nessuna versione pubblicata.</Text>}
      <ul className="version-list">
        {versions.data?.map((v) => (
          <li key={v.version}>
            <div className="inline">
              <Text weight="semibold">{v.version}</Text>
              <Text size={200} className="muted">
                {new Date(v.publishedAt).toLocaleString('it-IT')} · {v.publishedBy}
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
                Esporta
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function formatDay(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' })
}

function PromoteDialog({ ws, rs, version, onDone }: { ws: string; rs: string; version: string; onDone: () => Promise<void> }) {
  const [env, setEnv] = useState('prod')
  const [when, setWhen] = useState<'now' | 'date'>('now')
  const [day, setDay] = useState('')
  return (
    <FormDialog
      title={`Porta ${version} in un ambiente`}
      submitLabel="Conferma"
      canSubmit={when === 'now' || Boolean(day)}
      trigger={<Button size="small">Porta in…</Button>}
      onSubmit={async () => {
        await setAlias(ws, rs, env, version, when === 'date' ? day : null)
        await onDone()
      }}
    >
      <Field label="Ambiente">
        <Dropdown value={env} selectedOptions={[env]} onOptionSelect={(_, d) => setEnv(d.optionValue ?? 'prod')}>
          {ENVS.map((e) => (
            <Option key={e} value={e}>
              {e}
            </Option>
          ))}
        </Dropdown>
      </Field>
      <RadioGroup value={when} onChange={(_, d) => setWhen(d.value as 'now' | 'date')} aria-label="Quando">
        <Radio value="now" label="Da subito, senza data di inizio (sostituisce la versione attuale)" />
        <Radio value="date" label="Da una data: le chiamate con data di riferimento successiva useranno questa versione" />
      </RadioGroup>
      {when === 'date' && (
        <Field label="In vigore dal">
          <Input type="date" value={day} onChange={(_, d) => setDay(d.value)} />
        </Field>
      )}
    </FormDialog>
  )
}

function changeText(c: Change): string {
  const v = (x: unknown) => (x === undefined ? '' : JSON.stringify(x))
  if (c.kind === 'added') return `${c.path}: aggiunto ${v(c.to)}`
  if (c.kind === 'removed') return `${c.path}: rimosso (era ${v(c.from)})`
  return `${c.path}: ${v(c.from)} → ${v(c.to)}`
}

export function DiffDialog({ ws, rs, from }: { ws: string; rs: string; from: string }) {
  const [diff, setDiff] = useState<GraphDiff | null>(null)
  const [error, setError] = useState<unknown>(null)
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
          Confronta con il draft
        </Button>
      </DialogTrigger>
      <DialogSurface className="wide-dialog">
        <DialogBody>
          <DialogTitle>Da {from} al draft</DialogTitle>
          <DialogContent className="stack">
            <ErrorBar error={error} />
            {!diff && !error && <Spinner size="tiny" />}
            {diff?.identical && <Text>Nessuna differenza nelle regole (le posizioni sul canvas non contano).</Text>}
            {diff && !diff.identical && (
              <>
                {diff.nodes.added.length > 0 && (
                  <section>
                    <Text weight="semibold">Nodi aggiunti</Text>
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
                    <Text weight="semibold">Nodi rimossi</Text>
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
                    <Text weight="semibold">Nodo {n.id} modificato</Text>
                    <ul className="diff-list">
                      {n.changes.map((c) => (
                        <li key={c.path}>
                          <code>{changeText(c)}</code>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
                {(diff.edges.added.length > 0 || diff.edges.removed.length > 0) && (
                  <section>
                    <Text weight="semibold">Collegamenti</Text>
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
                    <Text weight="semibold">Impostazioni e costanti</Text>
                    <ul className="diff-list">
                      {diff.other.map((c) => (
                        <li key={c.path}>
                          <code>{changeText(c)}</code>
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
              <Button>Chiudi</Button>
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
  if (!graph) return null
  const settings = graph.settings ?? {}
  return (
    <div className="stack">
      <Field label="Modalità" hint="Raccogliere tutti gli errori è utile per i form; fermarsi al primo per i controlli bloccanti.">
        <Dropdown
          value={settings.mode === 'collect_all' ? 'Raccogli tutti gli errori' : 'Fermati al primo errore'}
          selectedOptions={[settings.mode ?? 'fail_fast']}
          onOptionSelect={(_, d) =>
            change((g) => ({ ...g, settings: { ...g.settings, mode: d.optionValue as 'fail_fast' | 'collect_all' } }))
          }
        >
          <Option value="fail_fast">Fermati al primo errore</Option>
          <Option value="collect_all">Raccogli tutti gli errori</Option>
        </Dropdown>
      </Field>
      <Field label="Lingua predefinita dei messaggi">
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
        <Field label={`Versione dello schema di ${entity}`}>
          <Dropdown
            value={schemaVersion ? `v${schemaVersion}` : 'Nessuno schema'}
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
        label="Costanti ($.vars)"
        hint="Valori di configurazione riusati dalle regole: soglie, date, listini."
        value={graph.constants ?? {}}
        onValid={(constants) => change((g) => ({ ...g, constants: constants as Record<string, unknown> }))}
        rows={14}
      />
    </div>
  )
}

export function IssueList({ issues, onSelect }: { issues: Issue[]; onSelect?: (where: string) => void }) {
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
          {i.message}
        </li>
      ))}
    </ul>
  )
}

export function NodeIO({ nodeId }: { nodeId: string }) {
  const simulation = useEditor((s) => s.simulation)
  if (!simulation) return null
  const entry = simulation.trace?.find((t) => t.nodeId === nodeId)
  const feedback = simulation.feedback.filter((f) => f.nodeId === nodeId)
  return (
    <section className="panel-section io">
      <Text weight="semibold">Ultima simulazione</Text>
      {!entry ? (
        <Text size={200}>Il nodo non è stato eseguito.</Text>
      ) : (
        <>
          <Text size={200}>
            Esito: <b>{entry.outcome}</b>
            {entry.port ? ` · uscita ${entry.port}` : ''}
            {entry.us !== undefined ? ` · ${entry.us} µs` : ''}
          </Text>
          {entry.output !== undefined && entry.output !== null && <pre className="mini">{JSON.stringify(entry.output, null, 2)}</pre>}
          {feedback.map((f, i) => (
            <Text key={i} size={200}>
              <code>{f.code}</code> {f.message}
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
