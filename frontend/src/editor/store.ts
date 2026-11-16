// State of the rule set being edited. One editor is open at a time, so a module-level store
// is enough; `load` resets it when a draft is (re)loaded.

import { create } from 'zustand'

import type { Draft, ExecutionResult, Issue } from '../api/types'
import type { RuleGraph } from '../rgd'

export type PanelTab = 'node' | 'simulate' | 'tests' | 'versions' | 'settings'

const HISTORY = 100
/** Changes closer than this are one undo step (typing in a field, nudging a value). */
const COALESCE_MS = 600

interface EditorState {
  graph: RuleGraph | null
  past: RuleGraph[]
  future: RuleGraph[]
  lastChange: number
  lockVersion: number
  schemaVersion: number | null
  dirty: boolean
  selected: string | null
  tab: PanelTab
  issues: Issue[]
  warnings: string[]
  validated: boolean
  simulation: ExecutionResult | null
  load: (draft: Draft) => void
  change: (update: (graph: RuleGraph) => RuleGraph, options?: { coalesce?: boolean }) => void
  undo: () => void
  redo: () => void
  setSchemaVersion: (version: number | null) => void
  saved: (lockVersion: number) => void
  select: (id: string | null) => void
  setTab: (tab: PanelTab) => void
  setValidation: (issues: Issue[], warnings: string[]) => void
  setSimulation: (result: ExecutionResult | null) => void
}

export const useEditor = create<EditorState>((set) => ({
  graph: null,
  past: [],
  future: [],
  lastChange: 0,
  lockVersion: 0,
  schemaVersion: null,
  dirty: false,
  selected: null,
  tab: 'node',
  issues: [],
  warnings: [],
  validated: false,
  simulation: null,
  load: (draft) =>
    set({
      graph: draft.graph,
      past: [],
      future: [],
      lastChange: 0,
      lockVersion: draft.lockVersion,
      schemaVersion: draft.schemaVersion,
      dirty: false,
      selected: null,
      issues: [],
      warnings: [],
      validated: false,
      simulation: null,
    }),
  change: (update, options) =>
    set((s) => {
      if (!s.graph) return {}
      const next = update(s.graph)
      if (next === s.graph) return {}
      const now = Date.now()
      const merge = (options?.coalesce ?? true) && now - s.lastChange < COALESCE_MS && s.past.length > 0
      const past = merge ? s.past : [...s.past, s.graph].slice(-HISTORY)
      return { graph: next, past, future: [], lastChange: now, dirty: true, validated: false }
    }),
  undo: () =>
    set((s) => {
      const previous = s.past.at(-1)
      if (!s.graph || !previous) return {}
      return {
        graph: previous,
        past: s.past.slice(0, -1),
        future: [s.graph, ...s.future],
        lastChange: 0,
        dirty: true,
        validated: false,
      }
    }),
  redo: () =>
    set((s) => {
      const next = s.future[0]
      if (!s.graph || !next) return {}
      return {
        graph: next,
        past: [...s.past, s.graph],
        future: s.future.slice(1),
        lastChange: 0,
        dirty: true,
        validated: false,
      }
    }),
  setSchemaVersion: (version) => set({ schemaVersion: version, dirty: true, validated: false }),
  saved: (lockVersion) => set({ lockVersion, dirty: false }),
  select: (id) => set((s) => ({ selected: id, tab: id ? 'node' : s.tab })),
  setTab: (tab) => set({ tab }),
  setValidation: (issues, warnings) => set({ issues, warnings, validated: true }),
  setSimulation: (simulation) => set({ simulation }),
}))
