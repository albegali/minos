// Types of the Rule Graph Document (RGD) v1 and conversion to React Flow elements.
// The authoritative schema is the Pydantic model in backend/src/minos/engine/model.py.

import type { Edge, Node } from '@xyflow/react'

export type NodeType =
  | 'start'
  | 'condition'
  | 'group'
  | 'set'
  | 'switch'
  | 'feedback'
  | 'decision_table'
  | 'subruleset'
  | 'end'

export interface RgdNode {
  id: string
  type: NodeType
  label?: string
  cases?: { name: string; when: unknown }[]
  outcome?: 'valid' | 'invalid' | 'warning'
  operator?: 'and' | 'or' | 'not'
  [key: string]: unknown
}

export interface RgdEdge {
  from: string
  to: string
  on?: string
}

export interface RuleGraph {
  rgdVersion: '1.0'
  ruleset: string
  version?: string
  schemaRef?: { entity: string; version: number }
  settings?: { mode?: 'fail_fast' | 'collect_all'; locale?: string; maxSteps?: number }
  constants?: Record<string, unknown>
  nodes: RgdNode[]
  edges: RgdEdge[]
  ui?: { positions?: Record<string, [number, number]>; [key: string]: unknown }
}

export type NodeStatus = 'idle' | 'pass' | 'fail' | 'error' | 'end'

export interface RuleNodeData extends Record<string, unknown> {
  rgd: RgdNode
  ports: string[]
  status: NodeStatus
}

export type RuleFlowNode = Node<RuleNodeData, 'rule'>

/** Output ports of a node, in display order. */
export function portsOf(node: RgdNode): string[] {
  switch (node.type) {
    case 'condition':
    case 'group':
    case 'decision_table':
    case 'subruleset':
      return ['pass', 'fail']
    case 'switch':
      return [...(node.cases ?? []).map((c) => c.name), 'default']
    case 'end':
      return []
    default:
      return ['next']
  }
}

/** Fallback layout when the document has no `ui.positions`: columns by depth from start. */
export function layered(graph: RuleGraph): Record<string, [number, number]> {
  const depth = new Map<string, number>()
  const start = graph.nodes.find((n) => n.type === 'start')
  const queue: string[] = start ? [start.id] : []
  if (start) depth.set(start.id, 0)
  while (queue.length > 0) {
    const id = queue.shift() as string
    for (const e of graph.edges.filter((edge) => edge.from === id)) {
      const d = (depth.get(id) ?? 0) + 1
      if ((depth.get(e.to) ?? -1) < d) {
        depth.set(e.to, d)
        queue.push(e.to)
      }
    }
  }
  const rows = new Map<number, number>()
  const out: Record<string, [number, number]> = {}
  for (const n of graph.nodes) {
    const d = depth.get(n.id) ?? 0
    const r = rows.get(d) ?? 0
    rows.set(d, r + 1)
    out[n.id] = [d * 240, r * 140]
  }
  return out
}

export function toFlow(
  graph: RuleGraph,
  status: Record<string, NodeStatus> = {},
  visitedEdges: Set<string> = new Set(),
): { nodes: RuleFlowNode[]; edges: Edge[] } {
  const positions = graph.ui?.positions ?? layered(graph)
  const nodes: RuleFlowNode[] = graph.nodes.map((n) => {
    const [x, y] = positions[n.id] ?? [0, 0]
    return {
      id: n.id,
      type: 'rule',
      position: { x, y: y + 200 },
      data: { rgd: n, ports: portsOf(n), status: status[n.id] ?? 'idle' },
    }
  })
  const edges: Edge[] = graph.edges.map((e) => {
    const port = e.on ?? 'next'
    const id = `${e.from}:${port}->${e.to}`
    const visited = visitedEdges.has(id)
    return {
      id,
      source: e.from,
      sourceHandle: port,
      target: e.to,
      label: port === 'next' ? undefined : port,
      className: `edge-${port === 'fail' ? 'fail' : 'ok'}${visited ? ' edge-visited' : ''}`,
      animated: visited,
    }
  })
  return { nodes, edges }
}

/** Edge ids walked by an execution, given the ordered list of visited node ids. */
export function edgesOnPath(graph: RuleGraph, path: string[]): Set<string> {
  const ids = new Set<string>()
  for (let i = 0; i < path.length - 1; i++) {
    const edge = graph.edges.find((e) => e.from === path[i] && e.to === path[i + 1])
    if (edge) ids.add(`${edge.from}:${edge.on ?? 'next'}->${edge.to}`)
  }
  return ids
}
