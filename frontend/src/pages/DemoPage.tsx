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

import invalidPlan from '../../../examples/inputs/studyplan-emba-invalid.json'
import validPlan from '../../../examples/inputs/studyplan-emba-valid.json'
import exampleGraph from '../../../examples/rulesets/aurora.studyplan.emba.json'
import { edgesOnPath, type NodeStatus, type RuleGraph, toFlow } from '../rgd'
import { RuleNode } from '../RuleNode'

// JSON imports are typed structurally (tuples widen to number[]): cast via unknown.
const graph = exampleGraph as unknown as RuleGraph
const nodeTypes = { rule: RuleNode }
const STATUS_COLOR: Record<NodeStatus, string> = {
  idle: '#adb5bd',
  pass: '#2f9e44',
  fail: '#e03131',
  error: '#e03131',
  end: '#3b5bdb',
}
const minimapColor = (node: { data: Record<string, unknown> }) =>
  STATUS_COLOR[(node.data.status as NodeStatus | undefined) ?? 'idle']
const initialFlow = toFlow(graph)
const SAMPLES: Record<string, unknown> = {
  'Piano valido': validPlan,
  'Piano non valido': invalidPlan,
}

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
  const [selected, setSelected] = useState<string | null>(null)
  const [sample, setSample] = useState<string>('Piano non valido')
  const [result, setResult] = useState<ExecutionResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  // Node state goes through React Flow's change handlers so that nodes get their measured
  // size (needed by fitView and the minimap); simulation results only patch status/edges.
  const [nodes, setNodes, onNodesChange] = useNodesState(initialFlow.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlow.edges)

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
  }, [result, setNodes, setEdges])

  const selectedNode = graph.nodes.find((n) => n.id === selected)

  async function simulate() {
    setRunning(true)
    setError(null)
    try {
      const res = await fetch(`/v1/exec/local/${graph.ruleset}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ input: SAMPLES[sample], options: { trace: 'summary' } }),
      })
      const body: unknown = await res.json()
      if (!res.ok && res.status !== 422) {
        throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
      }
      setResult(body as ExecutionResult)
    } catch (e) {
      setResult(null)
      setError(
        `Esecuzione non riuscita (${e instanceof Error ? e.message : String(e)}). ` +
          "Avvia l'API: cd backend && uv run uvicorn minos.api.app:app",
      )
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="app">
      <header className="toolbar">
        <div className="brand">
          <strong>Minos Studio</strong>
          <span className="muted">
            {graph.ruleset} · v{graph.version} · {graph.settings?.mode}
          </span>
        </div>
        <div className="actions">
          <select value={sample} onChange={(e) => setSample(e.target.value)} aria-label="Input">
            {Object.keys(SAMPLES).map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <button type="button" onClick={simulate} disabled={running}>
            {running ? 'Esecuzione…' : 'Simula'}
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="canvas" aria-label="Grafo delle regole">
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
                Esito: <span className={`outcome outcome-${result.outcome}`}>{result.outcome}</span>
              </h2>
              <p className="muted">
                Uscita da <code>{result.exit.nodeId}</code> ({result.exit.reason}) · motore{' '}
                {result.timing.engineUs} µs
              </p>
              <ul className="feedback">
                {result.feedback.map((f, i) => (
                  <li key={`${f.code}-${i}`} className={`sev-${f.severity}`}>
                    <code>{f.code}</code> {f.message}
                  </li>
                ))}
              </ul>
              <h3>Output</h3>
              <pre>{JSON.stringify(result.result, null, 2)}</pre>
            </section>
          )}

          {selectedNode ? (
            <section>
              <h3>Nodo {selectedNode.id}</h3>
              <pre>{JSON.stringify(selectedNode, null, 2)}</pre>
            </section>
          ) : (
            !result && (
              <p className="muted">
                Seleziona un nodo per vederne la configurazione, oppure premi Simula per eseguire
                il rule set sull'input scelto.
              </p>
            )
          )}
        </aside>
      </main>
    </div>
  )
}
