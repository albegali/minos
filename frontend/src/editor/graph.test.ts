import { describe, expect, it } from 'vitest'

import type { RuleGraph } from '../rgd'
import {
  addNode,
  canConnect,
  connect,
  defaultNode,
  disconnect,
  edgeId,
  issueNode,
  newNodeId,
  portsOf,
  pruneEdges,
  removeNode,
  renamePort,
  setPosition,
  updateNode,
  variableNames,
} from './graph'

const base = (): RuleGraph => ({
  rgdVersion: '1.0',
  ruleset: 't',
  constants: { minCfu: 60 },
  nodes: [
    { id: 'start', type: 'start' },
    { id: 'end', type: 'end', outcome: 'valid' },
  ],
  edges: [{ from: 'start', to: 'end' }],
})

describe('graph operations', () => {
  it('adds nodes with unique ids and default content', () => {
    let g = base()
    const id = newNodeId(g, 'condition')
    g = addNode(g, defaultNode('condition', id), [100, 50])
    expect(id).toBe('condition1')
    expect(newNodeId(g, 'condition')).toBe('condition2')
    expect(g.ui?.positions?.condition1).toEqual([100, 50])
    expect(g.nodes.find((n) => n.id === 'condition1')?.condition).toEqual({ op: '==', left: { ref: '' }, right: '' })
    expect(() => addNode(g, defaultNode('condition', 'condition1'), [0, 0])).toThrow()
    expect(() => addNode(g, defaultNode('start', 'start2'), [0, 0])).toThrow(/inizio/)
  })

  it.each(['group', 'set', 'switch', 'feedback', 'end', 'start'])('has defaults for %s', (type) => {
    expect(defaultNode(type, 'x').type).toBe(type)
  })

  it('freezes automatic positions on structural edits', () => {
    const g = connect(addNode(base(), defaultNode('condition', 'c'), [600, 0]), 'start', 'next', 'c')
    expect(Object.keys(g.ui?.positions ?? {}).sort()).toEqual(['c', 'end', 'start'])
    const before = g.ui?.positions?.end
    const after = connect(g, 'c', 'pass', 'end').ui?.positions?.end
    expect(after).toEqual(before)
  })

  it('connects ports, replacing the previous edge of the same port', () => {
    let g = addNode(base(), defaultNode('condition', 'c'), [0, 0])
    g = connect(g, 'start', 'next', 'c')
    expect(g.edges).toEqual([{ from: 'start', to: 'c' }])
    g = connect(g, 'c', 'pass', 'end')
    expect(g.edges.at(-1)).toEqual({ from: 'c', to: 'end', on: 'pass' })
    g = disconnect(g, edgeId({ from: 'c', to: 'end', on: 'pass' }))
    expect(g.edges).toEqual([{ from: 'start', to: 'c' }])
  })

  it('refuses invalid connections', () => {
    let g = addNode(base(), defaultNode('condition', 'c'), [0, 0])
    g = connect(g, 'start', 'next', 'c')
    expect(canConnect(g, 'c', 'pass', 'c').ok).toBe(false)
    expect(canConnect(g, 'c', 'pass', 'start').reason).toMatch(/inizio/)
    expect(canConnect(g, 'c', 'nope', 'end').reason).toMatch(/porta/)
    expect(canConnect(g, 'c', 'pass', 'ghost').ok).toBe(false)
    g = addNode(g, defaultNode('condition', 'd'), [0, 0])
    g = connect(g, 'c', 'pass', 'd')
    expect(canConnect(g, 'd', 'pass', 'c').reason).toMatch(/ciclo/)
    expect(() => connect(g, 'd', 'pass', 'c')).toThrow(/ciclo/)
  })

  it('removes a node with its edges and position', () => {
    let g = addNode(base(), defaultNode('condition', 'c'), [1, 2])
    g = connect(connect(g, 'start', 'next', 'c'), 'c', 'pass', 'end')
    g = removeNode(g, 'c')
    expect(g.nodes.map((n) => n.id)).toEqual(['start', 'end'])
    expect(g.edges).toEqual([])
    expect(g.ui?.positions?.c).toBeUndefined()
  })

  it('renames and prunes switch ports', () => {
    let g = addNode(base(), defaultNode('switch', 's'), [0, 0])
    g = connect(g, 's', 'caso1', 'end')
    const sw = g.nodes.find((n) => n.id === 's') ?? defaultNode('switch', 's')
    expect(portsOf(sw)).toEqual(['caso1', 'default'])
    const renamed = { ...sw, cases: [{ name: 'finance', when: true }] }
    g = renamePort(updateNode(g, 's', renamed), 's', 'caso1', 'finance')
    expect(g.edges.at(-1)?.on).toBe('finance')
    g = pruneEdges(updateNode(g, 's', { ...renamed, cases: [] }))
    expect(g.edges.some((e) => e.from === 's')).toBe(false)
  })

  it('reports ports per node type', () => {
    expect(portsOf({ id: 'a', type: 'condition' })).toEqual(['pass', 'fail'])
    expect(portsOf({ id: 'a', type: 'end' })).toEqual([])
    expect(portsOf({ id: 'a', type: 'set' })).toEqual(['next'])
  })

  it('lists variables and maps issues to nodes', () => {
    const g = addNode(base(), { id: 's', type: 'set', assign: { total: 1 } }, [0, 0])
    expect(variableNames(setPosition(g, 's', [5, 5]))).toEqual(['minCfu', 'total'])
    expect(issueNode('nodes.chkAge.condition.left')).toBe('chkAge')
    expect(issueNode('nodes.g.children[0]')).toBe('g')
    expect(issueNode('edges[2]')).toBeNull()
  })
})
