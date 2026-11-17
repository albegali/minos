import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Draft } from '../api/types'
import type { RuleGraph } from '../rgd'
import { useEditor } from './store'

const graph: RuleGraph = { rgdVersion: '1.0', ruleset: 't', nodes: [], edges: [] }
const draft: Draft = { graph, lockVersion: 1, schemaVersion: null, updatedBy: 'x', updatedAt: '' }
const label = (l: string) => (g: RuleGraph) => ({ ...g, ruleset: l })

describe('editor history', () => {
  afterEach(() => vi.useRealTimers())

  it('undoes and redoes changes, coalescing quick edits', () => {
    vi.useFakeTimers()
    const s = useEditor.getState()
    s.load(draft)
    s.change(label('a'))
    vi.advanceTimersByTime(1000)
    s.change(label('ab'))
    vi.advanceTimersByTime(100)
    s.change(label('abc')) // typed quickly: same step as 'ab'
    expect(useEditor.getState().past).toHaveLength(2)

    useEditor.getState().undo()
    expect(useEditor.getState().graph?.ruleset).toBe('a')
    useEditor.getState().undo()
    expect(useEditor.getState().graph?.ruleset).toBe('t')
    useEditor.getState().undo() // nothing left
    expect(useEditor.getState().graph?.ruleset).toBe('t')
    useEditor.getState().redo()
    useEditor.getState().redo()
    expect(useEditor.getState().graph?.ruleset).toBe('abc')
    useEditor.getState().redo() // nothing left
    expect(useEditor.getState().dirty).toBe(true)

    useEditor.getState().undo()
    vi.advanceTimersByTime(1000)
    useEditor.getState().change(label('x'), { coalesce: false })
    expect(useEditor.getState().future).toHaveLength(0)
    useEditor.getState().change((g) => g) // no-op: no history entry
    expect(useEditor.getState().past).toHaveLength(2)
  })
})

describe('saving', () => {
  it('keeps edits made while a save was in flight (UI-05)', () => {
    const s = useEditor.getState()
    s.load(draft)
    s.change(label('a'), { coalesce: false })
    const sent = useEditor.getState().graph as RuleGraph
    useEditor.getState().change(label('ab'), { coalesce: false }) // typed during the request
    useEditor.getState().saved(2, sent, null)
    expect(useEditor.getState()).toMatchObject({ lockVersion: 2, dirty: true })
    const latest = useEditor.getState().graph as RuleGraph
    useEditor.getState().saved(3, latest, null)
    expect(useEditor.getState()).toMatchObject({ lockVersion: 3, dirty: false })
  })

  it('keeps the simulator form across tabs and ties a result to its graph (UI-02)', () => {
    const s = useEditor.getState()
    s.load({ ...draft, graph: { ...graph, settings: { locale: 'en' } } })
    expect(useEditor.getState().simRequest.locale).toBe('en')
    useEditor.getState().setSimRequest({ input: { n: 1 } })
    useEditor.getState().setTab('node')
    expect(useEditor.getState().simRequest.input).toEqual({ n: 1 })
    const result = { outcome: 'valid' } as never
    useEditor.getState().setSimulation(result, useEditor.getState().simRequest)
    expect(useEditor.getState().simulated?.graph).toBe(useEditor.getState().graph)
    useEditor.getState().change(label('x'))
    expect(useEditor.getState().simulated?.graph).not.toBe(useEditor.getState().graph)
  })
})
