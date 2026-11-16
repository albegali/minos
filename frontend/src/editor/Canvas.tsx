import '@xyflow/react/dist/style.css'

import {
  Background,
  type Connection,
  Controls,
  type Edge,
  Handle,
  MiniMap,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import { type DragEvent, useCallback, useEffect, useMemo } from 'react'

import type { Catalog, NodeManifest } from '../api/types'
import { layered, type RgdNode, type RuleGraph } from '../rgd'
import { describe } from './expr'
import { addNode, canConnect, connect, defaultNode, disconnect, edgeId, issueNode, newNodeId, portsOf, removeNode, setPosition } from './graph'
import { useEditor } from './store'

export const DRAG_TYPE = 'application/minos-node'

type Status = 'idle' | 'pass' | 'fail' | 'error' | 'end'

interface Data extends Record<string, unknown> {
  rgd: RgdNode
  manifest?: NodeManifest
  ports: string[]
  status: Status
  issues: number
}

type FlowNode = Node<Data, 'rule'>

function summary(n: RgdNode): string | null {
  switch (n.type) {
    case 'condition':
      return describe(n.condition)
    case 'group':
      return `${(n.children as unknown[] | undefined)?.length ?? 0} regole · ${String(n.operator ?? 'and').toUpperCase()}`
    case 'set':
      return Object.keys((n.assign as object | undefined) ?? {}).join(', ')
    case 'feedback':
      return String((n.feedback as { code?: string } | undefined)?.code ?? '')
    case 'decision_table':
      return `${(n.rules as unknown[] | undefined)?.length ?? 0} righe → $.vars.${String(n.target ?? '')}`
    case 'subruleset':
      return `${String(n.ruleset || '?')}@${String(n.version || '?')}${n.forEach ? ' per ogni elemento' : ''}`
    case 'end':
      return n.outcome ?? 'valid'
    default:
      return null
  }
}

function RuleNodeView({ data, selected }: NodeProps<FlowNode>) {
  const { rgd, manifest, ports, status, issues } = data
  const text = summary(rgd)
  return (
    <div className={`rule-node type-${rgd.type} status-${status}${selected ? ' selected' : ''}${issues ? ' has-issues' : ''}`}>
      {rgd.type !== 'start' && <Handle type="target" position={Position.Left} />}
      <div className="rule-node-type">
        {manifest?.label.it ?? rgd.type}
        {issues > 0 && <span className="issue-dot" title={`${issues} problemi`}>{issues}</span>}
      </div>
      <div className="rule-node-label">{rgd.label || rgd.id}</div>
      {text && <div className="rule-node-summary" title={text}>{text}</div>}
      <div className="rule-node-ports">
        {ports.map((port, i) => (
          <div key={port} className={`rule-node-port port-${port}`}>
            {port !== 'next' && <span>{port}</span>}
            <Handle
              type="source"
              id={port}
              position={Position.Right}
              style={{ top: `${((i + 1) / (ports.length + 1)) * 100}%` }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

const nodeTypes = { rule: RuleNodeView }

const MINIMAP_COLOR: Record<Status, string> = {
  idle: '#b7c2ce',
  pass: '#01928c',
  fail: '#d64545',
  error: '#d64545',
  end: '#039bb0',
}

function statusMap(): Record<string, Status> {
  const sim = useEditor.getState().simulation
  const out: Record<string, Status> = {}
  for (const t of sim?.trace ?? []) out[t.nodeId] = t.outcome === 'pass' ? 'pass' : t.outcome === 'fail' ? 'fail' : 'error'
  if (sim) out[sim.exit.nodeId] = sim.exit.reason === 'end' ? 'end' : (out[sim.exit.nodeId] ?? 'fail')
  return out
}

export function Canvas({ graph, catalog }: { graph: RuleGraph; catalog: Catalog }) {
  const change = useEditor((s) => s.change)
  const select = useEditor((s) => s.select)
  const selected = useEditor((s) => s.selected)
  const issues = useEditor((s) => s.issues)
  const simulation = useEditor((s) => s.simulation)
  const { screenToFlowPosition, fitView } = useReactFlow()
  const manifests = useMemo(() => new Map(catalog.nodeTypes.map((m) => [m.type, m])), [catalog])

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // Sync React Flow's local state (which keeps measured sizes and selection) from the graph.
  useEffect(() => {
    const positions = { ...layered(graph), ...(graph.ui?.positions ?? {}) }
    const status = statusMap()
    const issueCount = new Map<string, number>()
    for (const i of issues) {
      const id = issueNode(i.where)
      if (id) issueCount.set(id, (issueCount.get(id) ?? 0) + 1)
    }
    setNodes((current) => {
      const prev = new Map(current.map((n) => [n.id, n]))
      return graph.nodes.map((n) => {
        const [x, y] = positions[n.id] ?? [0, 0]
        const old = prev.get(n.id)
        return {
          ...(old ?? {}),
          id: n.id,
          type: 'rule' as const,
          position: old?.dragging ? old.position : { x, y },
          selected: n.id === selected,
          data: {
            rgd: n,
            manifest: manifests.get(n.type),
            ports: portsOf(n, manifests.get(n.type)),
            status: status[n.id] ?? 'idle',
            issues: issueCount.get(n.id) ?? 0,
          },
        }
      })
    })
    const walked = new Set<string>()
    const path = simulation?.path ?? []
    for (let i = 0; i < path.length - 1; i++) {
      const e = graph.edges.find((x) => x.from === path[i] && x.to === path[i + 1])
      if (e) walked.add(edgeId(e))
    }
    setEdges((current) => {
      const prev = new Map(current.map((e) => [e.id, e]))
      return graph.edges.map((e) => {
        const id = edgeId(e)
        const port = e.on ?? 'next'
        return {
          ...(prev.get(id) ?? {}),
          id,
          source: e.from,
          sourceHandle: port,
          target: e.to,
          label: port === 'next' ? undefined : port,
          className: `edge-${port === 'fail' ? 'fail' : 'ok'}${walked.has(id) ? ' edge-visited' : ''}`,
          animated: walked.has(id),
        }
      })
    })
  }, [graph, issues, simulation, selected, manifests, setNodes, setEdges])

  // When nodes are added or removed, bring the whole graph back into view so that a new
  // node (and its ports) is never left outside the visible canvas.
  // The same when the side panel opens or closes and the canvas changes width.
  const nodeCount = graph.nodes.length
  const panelOpen = useEditor((s) => s.panelOpen)
  useEffect(() => {
    const handle = window.setTimeout(() => void fitView({ padding: 0.15, maxZoom: 1, duration: 200 }), 50)
    return () => window.clearTimeout(handle)
  }, [nodeCount, panelOpen, fitView])

  const onConnect = useCallback(
    (c: Connection) => {
      if (!c.source || !c.target) return
      try {
        change((g) => connect(g, c.source, c.sourceHandle ?? 'next', c.target))
      } catch {
        // invalid connections are filtered by isValidConnection; ignore races
      }
    },
    [change],
  )

  const isValidConnection = useCallback(
    (c: Connection | Edge) =>
      Boolean(c.source && c.target) &&
      canConnect(useEditor.getState().graph ?? graph, c.source, c.sourceHandle ?? 'next', c.target).ok,
    [graph],
  )

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault()
      const type = event.dataTransfer.getData(DRAG_TYPE)
      if (!type) return
      const p = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      const g = useEditor.getState().graph
      if (!g) return
      const id = newNodeId(g, type)
      try {
        change((current) => addNode(current, defaultNode(type, id), [Math.round(p.x), Math.round(p.y)]))
        select(id)
      } catch (err) {
        window.alert((err as Error).message)
      }
    },
    [change, select, screenToFlowPosition],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodesChange={(changes) => {
        const removable = changes.filter(
          (c) => c.type !== 'remove' || graph.nodes.find((n) => n.id === c.id)?.type !== 'start',
        )
        onNodesChange(removable)
        for (const c of removable) if (c.type === 'remove') change((g) => removeNode(g, c.id))
      }}
      onEdgesChange={(changes) => {
        onEdgesChange(changes)
        for (const c of changes) if (c.type === 'remove') change((g) => disconnect(g, c.id))
      }}
      onNodeDragStop={(_, node) => change((g) => setPosition(g, node.id, [Math.round(node.position.x), Math.round(node.position.y)]))}
      onConnect={onConnect}
      isValidConnection={isValidConnection}
      onNodeClick={(_, node) => select(node.id)}
      onPaneClick={() => select(null)}
      onDragOver={(e) => {
        e.preventDefault()
        e.dataTransfer.dropEffect = 'move'
      }}
      onDrop={onDrop}
      deleteKeyCode={['Delete', 'Backspace']}
      minZoom={0.2}
      fitView
      fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
    >
      <Background />
      <MiniMap pannable zoomable nodeColor={(n) => MINIMAP_COLOR[(n.data as Data).status]} />
      <Controls />
    </ReactFlow>
  )
}

export function Palette({ catalog, onAdd }: { catalog: Catalog; onAdd: (type: string) => void }) {
  return (
    <nav className="palette" aria-label="Palette dei nodi">
      {catalog.categories.map((cat) => (
        <div key={cat.key} className="palette-group">
          <div className="palette-title">{cat.label.it}</div>
          {catalog.nodeTypes
            .filter((m) => m.category === cat.key && !m.unique)
            .map((m) => (
              <button
                key={m.type}
                type="button"
                className={`palette-item type-${m.type}`}
                draggable
                title={`${m.description.it}. Trascina sul canvas o fai clic per aggiungere.`}
                onDragStart={(e) => {
                  e.dataTransfer.setData(DRAG_TYPE, m.type)
                  e.dataTransfer.effectAllowed = 'move'
                }}
                onClick={() => onAdd(m.type)}
              >
                <span className="palette-label">{m.label.it}</span>
                <span className="palette-desc">{m.description.it}</span>
              </button>
            ))}
        </div>
      ))}
    </nav>
  )
}
