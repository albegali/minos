import { describe, expect, it } from 'vitest'

import type { RuleGraph } from '../rgd'
import { autoLayout } from './layout'

describe('automatic layout', () => {
  it('places nodes left to right along the edges and separates branches', () => {
    const graph: RuleGraph = {
      rgdVersion: '1.0',
      ruleset: 't',
      nodes: [
        { id: 'start', type: 'start' },
        { id: 'c', type: 'condition' },
        { id: 'ok', type: 'end' },
        { id: 'ko', type: 'end' },
      ],
      edges: [
        { from: 'start', to: 'c' },
        { from: 'c', to: 'ok', on: 'pass' },
        { from: 'c', to: 'ko', on: 'fail' },
      ],
    }
    const p = autoLayout(graph)
    expect(p.start?.[0]).toBeLessThan(p.c?.[0] ?? 0)
    expect(p.c?.[0]).toBeLessThan(p.ok?.[0] ?? 0)
    expect(p.ok?.[0]).toBe(p.ko?.[0])
    expect(p.ok?.[1]).not.toBe(p.ko?.[1])
    expect(Object.keys(autoLayout({ ...graph, edges: [{ from: 'start', to: 'ghost' }] }))).toHaveLength(4)
  })
})
