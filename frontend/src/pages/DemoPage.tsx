import '@xyflow/react/dist/style.css'

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react'
import { useEffect, useState } from 'react'

import { edgesOnPath, type NodeStatus, type RuleGraph, toFlow } from '../rgd'
import { BrandLockup } from '../components/Brand'
import { LanguageSwitch } from '../components/LanguageSwitch'
import { useI18n } from '../i18n'
import { RuleNode } from '../RuleNode'

// Every example of the repository, bundled at build time. Inputs belong to the entity of
// the rule set: examples/inputs/<entity in lower case>-*.json.
const graphFiles = import.meta.glob<RuleGraph>('../../../examples/rulesets/*.json', { eager: true, import: 'default' })
const inputFiles = import.meta.glob<unknown>('../../../examples/inputs/*.json', { eager: true, import: 'default' })
const EXAMPLES = Object.values(graphFiles).sort((a, b) => a.ruleset.localeCompare(b.ruleset))

function samplesFor(graph: RuleGraph): Record<string, unknown> {
  const prefix = (graph.schemaRef?.entity ?? '').toLowerCase()
  const out: Record<string, unknown> = {}
  for (const [path, data] of Object.entries(inputFiles)) {
    const name = path.split('/').pop()?.replace(/\.json$/, '') ?? path
    if (name.startsWith(`${prefix}-`)) out[name.slice(prefix.length + 1)] = data
  }
  return out
}

const nodeTypes = { rule: RuleNode }
const STATUS_COLOR: Record<NodeStatus, string> = {
  idle: '#b7c2ce',
  pass: '#01928c',
  fail: '#d64545',
  error: '#d64545',
  end: '#039bb0',
}
const minimapColor = (node: { data: Record<string, unknown> }) =>
  STATUS_COLOR[(node.data.status as NodeStatus | undefined) ?? 'idle']

interface Feedback {
  code: string
  severity: 'info' | 'warning' | 'error'
  message: string
  nodeId: string
  path?: string
}

interface ExecutionResult {
  outcome: string
  exit: { nodeId: string; reason: string }
  feedback: Feedback[]
  result: Record<string, unknown>
  path: string[]
  trace: { nodeId: string; outcome: string }[] | null
  timing: { engineUs: number }
}

export function DemoPage() {
  const [ruleset, setRuleset] = useState(EXAMPLES.find((g) => g.ruleset.endsWith('emba'))?.ruleset ?? EXAMPLES[0]?.ruleset)
  const graph = EXAMPLES.find((g) => g.ruleset === ruleset)
  const { t } = useI18n()
  if (!graph) return <p>{t('demo.noExamples')}</p>
  // A key per rule set resets the canvas state when the example changes.
  return <DemoView key={graph.ruleset} graph={graph} onRuleset={setRuleset} />
}

function DemoView({ graph, onRuleset }: { graph: RuleGraph; onRuleset: (key: string) => void }) {
  const samples = samplesFor(graph)
  const [selected, setSelected] = useState<string | null>(null)
  const [sample, setSample] = useState<string>(Object.keys(samples).find((s) => s.includes('invalid')) ?? Object.keys(samples)[0] ?? '')
  const [result, setResult] = useState<ExecutionResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const { t, rich } = useI18n()

  // Node state goes through React Flow's change handlers so that nodes get their measured
  // size (needed by fitView and the minimap); simulation results only patch status/edges.
  const [nodes, setNodes, onNodesChange] = useNodesState(toFlow(graph).nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(toFlow(graph).edges)

  useEffect(() => {
    const status: Record<string, NodeStatus> = {}
    for (const t of result?.trace ?? []) {
      status[t.nodeId] = t.outcome === 'pass' ? 'pass' : t.outcome === 'fail' ? 'fail' : 'error'
    }
    if (result && graph.nodes.find((n) => n.id === result.exit.nodeId)?.type === 'end') {
      status[result.exit.nodeId] = 'end'
    }
    setNodes((current) =>
      current.map((n) => ({ ...n, data: { ...n.data, status: status[n.id] ?? 'idle' } })),
    )
    setEdges(toFlow(graph, status, edgesOnPath(graph, result?.path ?? [])).edges)
  }, [graph, result, setNodes, setEdges])

  const selectedNode = graph.nodes.find((n) => n.id === selected)

  async function simulate() {
    setRunning(true)
    setError(null)
    try {
      const res = await fetch(`/v1/exec/local/${graph.ruleset}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input: samples[sample], options: { trace: 'summary', referenceDate: '2027-09-20' } }),
      })
      const body: unknown = await res.json()
      if (!res.ok && res.status !== 422) {
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
      }
      setResult(body as ExecutionResult)
    } catch (e) {
      setResult(null)
      setError(t('demo.runFailed', { message: e instanceof Error ? e.message : String(e) }))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="app">
      <header className="toolbar">
        <div className="brand">
          <BrandLockup tagline="Demo" />
          <span className="muted">
            {graph.ruleset} · v{graph.version} · {graph.settings?.mode}
          </span>
        </div>
        <div className="actions">
          <select value={graph.ruleset} onChange={(e) => onRuleset(e.target.value)} aria-label={t('demo.example')}>
            {EXAMPLES.map((g) => (
              <option key={g.ruleset} value={g.ruleset}>
                {g.ruleset}
              </option>
            ))}
          </select>
          <select value={sample} onChange={(e) => setSample(e.target.value)} aria-label={t('demo.input')}>
            {Object.keys(samples).map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <LanguageSwitch />
          <button type="button" onClick={simulate} disabled={running}>
            {running ? t('demo.running') : t('demo.simulate')}
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="canvas" aria-label={t('demo.graph')}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            minZoom={0.2}
            fitViewOptions={{ padding: 0.1 }}
            onNodeClick={(_, node) => setSelected(node.id)}
            onPaneClick={() => setSelected(null)}
            nodesConnectable={false}
            fitView
          >
            <Background />
            <MiniMap pannable zoomable nodeColor={minimapColor} />
            <Controls />
          </ReactFlow>
        </section>

        <aside className="panel">
          {error && <p className="error">{error}</p>}

          {result && (
            <section>
              <h2>
                {rich('demo.outcome', {
                  outcome: <span className={`outcome outcome-${result.outcome}`}>{result.outcome}</span>,
                })}
              </h2>
              <p className="muted">
                {rich('demo.exit', {
                  node: <code>{result.exit.nodeId}</code>,
                  reason: result.exit.reason,
                  us: result.timing.engineUs,
                })}
              </p>
              <ul className="feedback">
                {result.feedback.map((f, i) => (
                  <li key={`${f.code}-${i}`} className={`sev-${f.severity}`}>
                    <code>{f.code}</code> {f.message}
                  </li>
                ))}
              </ul>
              <h3>{t('demo.output')}</h3>
              <pre>{JSON.stringify(result.result, null, 2)}</pre>
            </section>
          )}

          {selectedNode ? (
            <section>
              <h3>{t('demo.node', { id: selectedNode.id })}</h3>
              <pre>{JSON.stringify(selectedNode, null, 2)}</pre>
            </section>
          ) : (
            !result && (
              <p className="muted">{t('demo.hint')}</p>
            )
          )}
        </aside>
      </main>
    </div>
  )
}
