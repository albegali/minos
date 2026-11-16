// Pure, immutable operations on a Rule Graph Document. The editor store applies them; unit
// tests cover them without a browser.

import type { NodeManifest } from '../api/types'
import { layered, type RgdEdge, type RgdNode, type RuleGraph } from '../rgd'
import { omit } from '../util'
import { blankComparison } from './expr'

export type Position = [number, number]

export function portsOf(node: RgdNode, manifest?: NodeManifest): string[] {
  if (node.type === 'switch') return [...(node.cases ?? []).map((c) => c.name), 'default']
  if (manifest) return manifest.ports
  switch (node.type) {
    case 'condition':
    case 'group':
    case 'decision_table':
    case 'subruleset':
      return ['pass', 'fail']
    case 'end':
      return []
    default:
      return ['next']
  }
}

export function newNodeId(graph: RuleGraph, type: string): string {
  const taken = new Set(graph.nodes.map((n) => n.id))
  for (let i = 1; ; i++) {
    const id = `${type}${i}`
    if (!taken.has(id)) return id
  }
}

/** A new node of `type` with sensible, editable defaults. */
export function defaultNode(type: string, id: string): RgdNode {
  switch (type) {
    case 'condition':
      return { id, type, label: 'Nuova condizione', condition: blankComparison() }
    case 'group':
      return {
        id,
        type,
        label: 'Nuovo gruppo',
        operator: 'and',
        evaluate: 'all',
        children: [{ rule: blankComparison() }],
      }
    case 'set':
      return { id, type, label: 'Nuovo calcolo', assign: { nuovaVariabile: 0 } }
    case 'switch':
      return { id, type, label: 'Nuovo switch', cases: [{ name: 'caso1', when: blankComparison() }] }
    case 'feedback':
      return {
        id,
        type,
        label: 'Nuovo messaggio',
        feedback: { code: 'MSG', severity: 'info', message: { it: '' } },
      }
    case 'decision_table':
      return {
        id,
        type,
        label: 'Nuova tabella',
        hitPolicy: 'first',
        inputs: [{ name: 'input', label: 'input', expr: { ref: '' } }],
        outputs: [{ name: 'risultato', label: 'risultato' }],
        rules: [{ when: [null], then: { risultato: null } }],
        target: `${id}Result`,
      }
    case 'subruleset':
      return { id, type, label: 'Rule set annidato', ruleset: '', version: '', target: `${id}Result` }
    case 'end':
      return { id, type, label: 'Fine', outcome: 'valid' }
    default:
      return { id, type: type as RgdNode['type'] }
  }
}

function withPositions(graph: RuleGraph, positions: Record<string, Position>): RuleGraph {
  return { ...graph, ui: { ...graph.ui, positions } }
}

/**
 * Positions of every node, saved ones first and the automatic layout for the rest. Edits
 * store them all, so nodes never jump around when edges change the automatic layout.
 */
export function frozenPositions(graph: RuleGraph): Record<string, Position> {
  return { ...layered(graph), ...(graph.ui?.positions ?? {}) }
}

export function addNode(graph: RuleGraph, node: RgdNode, position: Position): RuleGraph {
  if (graph.nodes.some((n) => n.id === node.id)) throw new Error(`duplicate node id ${node.id}`)
  if (node.type === 'start' && graph.nodes.some((n) => n.type === 'start')) {
    throw new Error('il grafo ha già un nodo di inizio')
  }
  const positions = { ...frozenPositions(graph), [node.id]: position }
  return withPositions({ ...graph, nodes: [...graph.nodes, node] }, positions)
}

export function removeNode(graph: RuleGraph, id: string): RuleGraph {
  const positions = omit({ ...(graph.ui?.positions ?? {}) }, id)
  return withPositions(
    {
      ...graph,
      nodes: graph.nodes.filter((n) => n.id !== id),
      edges: graph.edges.filter((e) => e.from !== id && e.to !== id),
    },
    positions,
  )
}

export function updateNode(graph: RuleGraph, id: string, next: RgdNode): RuleGraph {
  return { ...graph, nodes: graph.nodes.map((n) => (n.id === id ? next : n)) }
}

export function setPosition(graph: RuleGraph, id: string, position: Position): RuleGraph {
  return withPositions(graph, { ...(graph.ui?.positions ?? {}), [id]: position })
}

export function edgeId(e: RgdEdge): string {
  return `${e.from}:${e.on ?? 'next'}->${e.to}`
}

export interface ConnectionCheck {
  ok: boolean
  reason?: string
}

export function canConnect(graph: RuleGraph, from: string, port: string, to: string): ConnectionCheck {
  if (from === to) return { ok: false, reason: 'un nodo non può collegarsi a sé stesso' }
  const target = graph.nodes.find((n) => n.id === to)
  if (!target) return { ok: false, reason: 'nodo di destinazione inesistente' }
  if (target.type === 'start') return { ok: false, reason: "non si può entrare nel nodo di inizio" }
  const source = graph.nodes.find((n) => n.id === from)
  if (!source || !portsOf(source).includes(port)) return { ok: false, reason: 'porta inesistente' }
  if (reaches(graph, to, from)) return { ok: false, reason: 'il collegamento creerebbe un ciclo' }
  return { ok: true }
}

function reaches(graph: RuleGraph, start: string, target: string): boolean {
  const seen = new Set<string>()
  const todo = [start]
  while (todo.length > 0) {
    const id = todo.pop() as string
    if (id === target) return true
    if (seen.has(id)) continue
    seen.add(id)
    for (const e of graph.edges) if (e.from === id) todo.push(e.to)
  }
  return false
}

/** Connect `from:port` to `to`, replacing whatever that port was connected to. */
export function connect(graph: RuleGraph, from: string, port: string, to: string): RuleGraph {
  const check = canConnect(graph, from, port, to)
  if (!check.ok) throw new Error(check.reason)
  const edges = graph.edges.filter((e) => !(e.from === from && (e.on ?? 'next') === port))
  const edge: RgdEdge = port === 'next' ? { from, to } : { from, to, on: port }
  return withPositions({ ...graph, edges: [...edges, edge] }, frozenPositions(graph))
}

export function disconnect(graph: RuleGraph, id: string): RuleGraph {
  return withPositions(
    { ...graph, edges: graph.edges.filter((e) => edgeId(e) !== id) },
    frozenPositions(graph),
  )
}

/** Rename a switch case and keep its outgoing edge. */
export function renamePort(graph: RuleGraph, nodeId: string, from: string, to: string): RuleGraph {
  return {
    ...graph,
    edges: graph.edges.map((e) => (e.from === nodeId && e.on === from ? { ...e, on: to } : e)),
  }
}

/** Drop edges whose port no longer exists (e.g. a removed switch case). */
export function pruneEdges(graph: RuleGraph): RuleGraph {
  const ports = new Map(graph.nodes.map((n) => [n.id, new Set(portsOf(n))]))
  return { ...graph, edges: graph.edges.filter((e) => ports.get(e.from)?.has(e.on ?? 'next')) }
}

/** Variables available as `$.vars.*`: constants plus every name assigned by a set node. */
export function variableNames(graph: RuleGraph): string[] {
  const names = new Set(Object.keys((graph.constants as Record<string, unknown> | undefined) ?? {}))
  for (const n of graph.nodes) {
    if (n.type === 'set' && n.assign && typeof n.assign === 'object') {
      Object.keys(n.assign as Record<string, unknown>).forEach((k) => names.add(k))
    }
    if ((n.type === 'decision_table' || n.type === 'subruleset') && typeof n.target === 'string' && n.target) {
      names.add(n.target)
    }
  }
  return [...names].sort()
}

/** Node id targeted by an issue location such as `nodes.chkAge.condition.left`. */
export function issueNode(where: string): string | null {
  const m = /^nodes\.([^.[]+)/.exec(where)
  return m?.[1] ?? null
}
