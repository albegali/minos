// State of the rule set being edited. One editor is open at a time, so a module-level store
// is enough; `load` resets it when a draft is (re)loaded.

import { create } from 'zustand'

import type { Draft, ExecutionResult, Issue } from '../api/types'
import type { RuleGraph } from '../rgd'

export type PanelTab = 'node' | 'simulate' | 'tests' | 'versions' | 'settings'

/** What the simulator runs: kept here so it survives switching panel tabs. */
export interface SimRequest {
  input: unknown
  referenceDate: string
  locale: string
}

/** The request behind the current simulation, and the graph it ran on. */
export interface Simulated extends SimRequest {
  graph: RuleGraph | null
}

function blankRequest(graph: RuleGraph | null): SimRequest {
  return { input: {}, referenceDate: '', locale: graph?.settings?.locale ?? 'it' }
}

const HISTORY = 100
/** Changes closer than this are one undo step (typing in a field, nudging a value). */
const COALESCE_MS = 600

interface EditorState {
  /** Which rule set the state belongs to (`workspace/ruleset`), set by `load`. */
  key: string | null
  graph: RuleGraph | null
  past: RuleGraph[]
  future: RuleGraph[]
  lastChange: number
  lockVersion: number
  schemaVersion: number | null
  dirty: boolean
  selected: string | null
  tab: PanelTab
  /** Whether the side panel is expanded; collapsed it leaves a slim rail of tab icons. */
  panelOpen: boolean
  issues: Issue[]
  warnings: string[]
  validated: boolean
  simulation: ExecutionResult | null
  simulated: Simulated | null
  simRequest: SimRequest
  load: (draft: Draft, key?: string | null) => void
  change: (update: (graph: RuleGraph) => RuleGraph, options?: { coalesce?: boolean }) => void
  undo: () => void
  redo: () => void
  setSchemaVersion: (version: number | null) => void
  /** The draft was saved as `graph` (and `schemaVersion`): edits made meanwhile stay dirty. */
  saved: (lockVersion: number, graph: RuleGraph, schemaVersion: number | null) => void
  select: (id: string | null) => void
  setTab: (tab: PanelTab) => void
  setPanelOpen: (open: boolean) => void
  setValidation: (issues: Issue[], warnings: string[]) => void
  setSimulation: (result: ExecutionResult | null, request?: SimRequest) => void
  setSimRequest: (patch: Partial<SimRequest>) => void
}

export const useEditor = create<EditorState>((set, get) => ({
  key: null,
  graph: null,
  past: [],
  future: [],
  lastChange: 0,
  lockVersion: 0,
  schemaVersion: null,
  dirty: false,
  selected: null,
  tab: 'node',
  panelOpen: true,
  issues: [],
  warnings: [],
  validated: false,
  simulation: null,
  simulated: null,
  simRequest: blankRequest(null),
  load: (draft, key = null) =>
    set({
      key,
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
      simulated: null,
      simRequest: blankRequest(draft.graph),
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
  saved: (lockVersion, graph, schemaVersion) =>
    set((s) => ({ lockVersion, dirty: s.graph !== graph || s.schemaVersion !== schemaVersion })),
  select: (id) => set((s) => (id ? { selected: id, tab: 'node', panelOpen: true } : { selected: null, tab: s.tab })),
  setTab: (tab) => set({ tab, panelOpen: true }),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  setValidation: (issues, warnings) => set({ issues, warnings, validated: true }),
  setSimulation: (simulation, request) =>
    set({ simulation, simulated: simulation && request ? { ...request, graph: get().graph } : null }),
  setSimRequest: (patch) => set((s) => ({ simRequest: { ...s.simRequest, ...patch } })),
}))
