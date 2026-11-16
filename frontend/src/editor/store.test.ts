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
