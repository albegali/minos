// Automatic left-to-right layout of a rule graph (dagre), used by the "Riordina" command.

import dagre from '@dagrejs/dagre'

import type { RuleGraph } from '../rgd'
import type { Position } from './graph'

const WIDTH = 220
const HEIGHT = 110

/** Positions for every node: ranks left to right, branches stacked vertically. */
export function autoLayout(graph: RuleGraph, sizes: Record<string, { width: number; height: number }> = {}): Record<string, Position> {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 70, marginx: 0, marginy: 0 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of graph.nodes) {
    const size = sizes[n.id] ?? { width: WIDTH, height: HEIGHT }
    g.setNode(n.id, { width: size.width, height: size.height })
  }
  for (const e of graph.edges) {
    if (g.hasNode(e.from) && g.hasNode(e.to)) g.setEdge(e.from, e.to)
  }
  dagre.layout(g)
  const out: Record<string, Position> = {}
  for (const n of graph.nodes) {
    const p = g.node(n.id)
    // dagre gives centres; React Flow positions are top-left corners
    out[n.id] = [Math.round(p.x - p.width / 2), Math.round(p.y - p.height / 2)]
  }
  return out
}
