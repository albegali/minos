// State of the rule set being edited. One editor is open at a time, so a module-level store
// is enough; `load` resets it when a draft is (re)loaded.

import { create } from 'zustand'

import type { Draft, ExecutionResult, Issue } from '../api/types'
import type { RuleGraph } from '../rgd'

export type PanelTab = 'node' | 'simulate' | 'tests' | 'versions' | 'settings'

interface EditorState {
  graph: RuleGraph | null
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
  change: (update: (graph: RuleGraph) => RuleGraph) => void
  setSchemaVersion: (version: number | null) => void
  saved: (lockVersion: number) => void
  select: (id: string | null) => void
  setTab: (tab: PanelTab) => void
  setValidation: (issues: Issue[], warnings: string[]) => void
  setSimulation: (result: ExecutionResult | null) => void
}

export const useEditor = create<EditorState>((set) => ({
  graph: null,
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
      lockVersion: draft.lockVersion,
      schemaVersion: draft.schemaVersion,
      dirty: false,
      selected: null,
      issues: [],
      warnings: [],
      validated: false,
      simulation: null,
    }),
  change: (update) =>
    set((s) => (s.graph ? { graph: update(s.graph), dirty: true, validated: false } : {})),
  setSchemaVersion: (version) => set({ schemaVersion: version, dirty: true, validated: false }),
  saved: (lockVersion) => set({ lockVersion, dirty: false }),
  select: (id) => set((s) => ({ selected: id, tab: id ? 'node' : s.tab })),
  setTab: (tab) => set({ tab }),
  setValidation: (issues, warnings) => set({ issues, warnings, validated: true }),
  setSimulation: (simulation) => set({ simulation }),
}))
