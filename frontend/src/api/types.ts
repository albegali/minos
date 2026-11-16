// Shapes of the Management API responses (see docs/api.md).

import type { RuleGraph } from '../rgd'

export type Localized = Record<string, string>

export interface Workspace {
  slug: string
  name: string
}

export interface Entity {
  key: string
  name: string
  description: string | null
}

export type JsonSchema = Record<string, unknown>

export interface SchemaVersion {
  version: number
  source: string
  hash: string
  createdBy: string
  createdAt: string
  schema?: JsonSchema
}

export interface RulesetSummary {
  key: string
  name: string
}

export interface ScheduleEntry {
  version: string
  /** ISO date, or null for the entry that applies with no start date. */
  effectiveFrom: string | null
}

export interface RulesetInfo extends RulesetSummary {
  entity: string | null
  description: string | null
  latestVersion: string | null
  /** Version each environment runs today. */
  aliases: Record<string, string>
  schedule: Record<string, ScheduleEntry[]>
}

export interface Change {
  path: string
  kind: 'added' | 'removed' | 'changed'
  from?: unknown
  to?: unknown
}

export interface GraphDiff {
  from: string
  to: string
  identical: boolean
  nodes: {
    added: { id: string; type: string; label?: string }[]
    removed: { id: string; type: string; label?: string }[]
    changed: { id: string; type: string; changes: Change[] }[]
  }
  edges: { added: string[]; removed: string[] }
  other: Change[]
}

export interface ImportResult {
  ruleset: string
  created: boolean
  entity: string
  entityCreated: boolean
  schemaVersion: number | null
  tests: number
  dependencies: { ruleset: string; version: string }[]
}

export interface Draft {
  graph: RuleGraph
  lockVersion: number
  schemaVersion: number | null
  updatedBy: string
  updatedAt: string
}

export interface Issue {
  where: string
  message: string
}

export interface Validation {
  valid: boolean
  issues: Issue[]
  warnings: string[]
}

export interface Feedback {
  code: string
  severity: 'info' | 'warning' | 'error'
  message: string
  nodeId: string
  path?: string
  data?: Record<string, unknown>
}

export interface TraceEntry {
  nodeId: string
  type: string
  outcome: 'pass' | 'fail' | 'error'
  port?: string
  output?: unknown
  us?: number
}

export interface ExecutionResult {
  requestId: string
  ruleset: string
  version: string
  outcome: 'valid' | 'invalid' | 'warning' | 'error'
  exit: { nodeId: string; reason: string }
  feedback: Feedback[]
  result: Record<string, unknown>
  path: string[]
  trace: TraceEntry[] | null
  timing: { engineUs: number }
}

export interface Expected {
  outcome?: string
  exitNodeId?: string
  feedbackCodes?: string[]
  result?: Record<string, unknown>
}

export interface TestCase {
  name: string
  input: unknown
  expected: Expected
  referenceDate: string | null
}

export interface TestRun {
  passed: boolean
  tests: { name: string; passed: boolean; differences: string[] }[]
}

export interface Version {
  version: string
  hash: string
  status: string
  notes: string | null
  publishedBy: string
  publishedAt: string
  tests?: TestRun['tests']
}

export interface NodeManifest {
  type: string
  category: string
  icon: string
  label: Localized
  description: Localized
  ports: string[]
  requiredPorts: string[]
  dynamicPorts?: 'cases'
  unique?: boolean
  params: JsonSchema
}

export interface OperatorSpec {
  op: string
  kind: 'compare' | 'unary' | 'logic' | 'range' | 'arith' | 'if'
  label: Localized
  types?: string[]
  formats?: string[]
  rightList?: boolean
  rightLiteral?: boolean
}

export interface FunctionSpec {
  fn: string
  label: Localized
  returns: string
  aggregate?: boolean
  args?: number | string
}

export interface Catalog {
  rgdVersion: string
  categories: { key: string; label: Localized }[]
  nodeTypes: NodeManifest[]
  operators: OperatorSpec[]
  functions: FunctionSpec[]
  roots: string[]
  metaKeys: string[]
}
