// Shapes of the Management API responses (see docs/api.md).

import type { RuleGraph } from '../rgd'

export type Localized = Record<string, string>

export type WorkspaceRole = 'viewer' | 'author' | 'publisher' | 'admin'
export type OrgRole = 'member' | 'admin' | 'owner'

export interface Workspace {
  slug: string
  name: string
  /** Slug of the organization the workspace belongs to. */
  organization?: string | null
  /** The caller's role in the workspace. */
  role?: WorkspaceRole
}

export interface Organization {
  slug: string
  name: string
  /** The user's role in it (absent for administrators of the installation). */
  role?: OrgRole
}

export interface User {
  id: string
  name: string
  /** Primary address: how the audit names the person. */
  email: string
  /** Every address of the account: any of them signs in. */
  emails: string[]
}

/** A sign-in: the user, the organization the session works in, all of theirs. */
export interface SessionInfo {
  user: User
  organization: Organization | null
  organizations: Organization[]
  expiresAt: string
  token?: string
}

export interface Member {
  id: string
  name: string
  email: string
  emails: string[]
  role: OrgRole
  workspaces: { workspace: string; role: WorkspaceRole }[]
  disabled: boolean
}

export interface WorkspaceMember {
  id: string
  name: string
  email: string
  role: WorkspaceRole
  /** Admin because owner or admin of the organization. */
  inherited: boolean
}

export interface Invitation {
  id: string
  email: string
  role: OrgRole
  workspaces: { workspace: string; role: WorkspaceRole }[]
  invitedBy: string
  createdAt: string
  expiresAt: string
  /** Only in the response that creates it. */
  token?: string
  url?: string
}

export interface InvitationPreview {
  organization: { slug: string; name: string }
  email: string
  role: OrgRole
  invitedBy: string
  expiresAt: string
  accountExists: boolean
}

export interface Entity {
  key: string
  name: string
  description: string | null
}

export type JsonSchema = Record<string, unknown>

export interface EntityInfo extends Entity {
  /** Entities whose latest schema uses this one as a field type. */
  usedBy: string[]
}

export interface SchemaReference {
  entity: string
  version: number
  /** Latest version of the referenced entity: newer than `version` means it can move. */
  latest: number | null
}

export interface SchemaVersion {
  version: number
  source: string
  hash: string
  createdBy: string
  createdAt: string
  /** As written, with entity references pinned (`entity:Course@2`). */
  schema?: JsonSchema
  /** Standalone form, referenced entities embedded under `$defs`: what rules read. */
  resolved?: JsonSchema
  references?: SchemaReference[]
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
