// TanStack Query hooks over the Management API.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { RuleGraph } from '../rgd'
import { api, request } from './client'
import type {
  Catalog,
  Draft,
  Entity,
  EntityInfo,
  ExecutionResult,
  GraphDiff,
  ImportResult,
  Invitation,
  InvitationPreview,
  JsonSchema,
  Member,
  OrgRole,
  RulesetInfo,
  RulesetSummary,
  SchemaVersion,
  TestCase,
  TestRun,
  Validation,
  SessionInfo,
  Version,
  Workspace,
  WorkspaceMember,
  WorkspaceRole,
} from './types'

const ws = (slug: string) => `/workspaces/${encodeURIComponent(slug)}`
const rs = (slug: string, key: string) => `${ws(slug)}/rulesets/${encodeURIComponent(key)}`

export const keys = {
  info: ['info'] as const,
  workspaces: ['workspaces'] as const,
  catalog: ['catalog'] as const,
  entities: (w: string) => ['entities', w] as const,
  entity: (w: string, e: string) => ['entity', w, e] as const,
  schemas: (w: string, e: string) => ['schemas', w, e] as const,
  schema: (w: string, e: string, v: number) => ['schema', w, e, v] as const,
  rulesets: (w: string) => ['rulesets', w] as const,
  ruleset: (w: string, r: string) => ['ruleset', w, r] as const,
  draft: (w: string, r: string) => ['draft', w, r] as const,
  versions: (w: string, r: string) => ['versions', w, r] as const,
  tests: (w: string, r: string) => ['tests', w, r] as const,
  members: (o: string) => ['members', o] as const,
  invitations: (o: string) => ['invitations', o] as const,
  workspaceMembers: (w: string) => ['workspaceMembers', w] as const,
}

export interface ServerInfo {
  name: string
  version: string
  authRequired: boolean
  management: boolean
  database: boolean
  /** New organizations can be registered from the Studio (MINOS_ALLOW_SIGNUP). */
  signup?: boolean
}

/** Public description of the installation: does it need API keys, has it a database? */
export function useServerInfo() {
  return useQuery({ queryKey: keys.info, queryFn: () => api<ServerInfo>('/info'), staleTime: Infinity })
}

export function useWorkspaces() {
  return useQuery({ queryKey: keys.workspaces, queryFn: () => api<Workspace[]>('/workspaces') })
}

/** The caller's role in a workspace (undefined while loading or when unknown). */
export function useWorkspaceRole(w: string): WorkspaceRole | undefined {
  const list = useWorkspaces()
  return list.data?.find((x) => x.slug === w)?.role
}

const ROLE_ORDER: WorkspaceRole[] = ['viewer', 'author', 'publisher', 'admin']

/** Whether `role` includes `needed`; an unknown role (old server, loading) is not limited. */
export function roleAllows(role: WorkspaceRole | undefined, needed: WorkspaceRole): boolean {
  return role === undefined || ROLE_ORDER.indexOf(role) >= ROLE_ORDER.indexOf(needed)
}

// ----------------------------------------------------------------------------- sign-in

export const signIn = (email: string, password: string, organization?: string) =>
  api<SessionInfo & { token: string }>('/auth/login', {
    method: 'POST',
    body: { email, password, organization },
    keepSessionOn401: true,
  })

/** Register an organization: as the signed-in user, or with an e-mail address and password
 * (an existing account's, or a new account's with `name`). */
export const signUp = (body: {
  organization: { slug: string; name: string }
  name?: string
  email?: string
  password?: string
}) => api<SessionInfo & { token: string }>('/auth/signup', { method: 'POST', body, keepSessionOn401: true })

export const signOut = () => api<null>('/auth/logout', { method: 'POST', keepSessionOn401: true })

export const chooseOrganization = (organization: string) =>
  api<SessionInfo>('/auth/organization', { method: 'POST', body: { organization } })

export const changePassword = (current: string, next: string) =>
  api<null>('/auth/password', { method: 'PUT', body: { current, new: next } })

export const fetchInvitation = (token: string) =>
  api<InvitationPreview>(`/auth/invitations/${encodeURIComponent(token)}`, { keepSessionOn401: true })

export const acceptInvitation = (token: string, body: { name?: string; password?: string }) =>
  api<SessionInfo & { token: string }>(`/auth/invitations/${encodeURIComponent(token)}/accept`, {
    method: 'POST',
    body,
    keepSessionOn401: true,
  })

// ----------------------------------------------------------------------------- organizations

/** Organizations the caller can see: theirs (users) or all (administrators). */
export function useOrganizations(enabled = true) {
  return useQuery({
    queryKey: ['organizations'],
    queryFn: () => api<import('./types').Organization[]>('/organizations'),
    enabled,
  })
}

const org = (slug: string) => `/organizations/${encodeURIComponent(slug)}`

export function useMembers(o: string | undefined) {
  return useQuery({
    queryKey: keys.members(o ?? ''),
    queryFn: () => api<Member[]>(`${org(o ?? '')}/members`),
    enabled: Boolean(o),
  })
}

export function useInvitations(o: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.invitations(o ?? ''),
    queryFn: () => api<Invitation[]>(`${org(o ?? '')}/invitations`),
    enabled: Boolean(o) && enabled,
  })
}

export function useInvite(o: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; role: OrgRole; workspaces: { workspace: string; role: WorkspaceRole }[] }) =>
      api<Invitation>(`${org(o)}/invitations`, { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.invitations(o) }),
  })
}

export function useRevokeInvitation(o: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<null>(`${org(o)}/invitations/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.invitations(o) }),
  })
}

export function useSetMemberRole(o: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, role }: { id: string; role: OrgRole }) =>
      api<null>(`${org(o)}/members/${encodeURIComponent(id)}`, { method: 'PUT', body: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.members(o) }),
  })
}

export function useRemoveMember(o: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<null>(`${org(o)}/members/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.members(o) }),
  })
}

export function useWorkspaceMembers(w: string) {
  return useQuery({
    queryKey: keys.workspaceMembers(w),
    queryFn: () => api<WorkspaceMember[]>(`${ws(w)}/members`),
  })
}

export function useSetWorkspaceRole(w: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, role }: { id: string; role: WorkspaceRole | null }) =>
      role
        ? api<null>(`${ws(w)}/members/${encodeURIComponent(id)}`, { method: 'PUT', body: { role } })
        : api<null>(`${ws(w)}/members/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.workspaceMembers(w) })
      void qc.invalidateQueries({ queryKey: ['members'] })
    },
  })
}

export function useCatalog() {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: () => api<Catalog>('/node-types'),
    staleTime: Infinity,
  })
}

export function useEntities(w: string) {
  return useQuery({ queryKey: keys.entities(w), queryFn: () => api<Entity[]>(`${ws(w)}/entities`) })
}

export function useEntity(w: string, e: string) {
  return useQuery({
    queryKey: keys.entity(w, e),
    queryFn: () => api<EntityInfo>(`${ws(w)}/entities/${encodeURIComponent(e)}`),
  })
}

export function useSchemas(w: string, e: string) {
  return useQuery({
    queryKey: keys.schemas(w, e),
    queryFn: () => api<SchemaVersion[]>(`${ws(w)}/entities/${encodeURIComponent(e)}/schemas`),
    enabled: Boolean(e), // the editor knows the entity only once the rule set has loaded
  })
}

export function useSchema(w: string, e: string, v: number | null | undefined) {
  return useQuery({
    queryKey: keys.schema(w, e, v ?? 0),
    queryFn: () => api<SchemaVersion>(`${ws(w)}/entities/${encodeURIComponent(e)}/schemas/${v}`),
    enabled: Boolean(e && v),
    staleTime: Infinity, // schema versions are immutable
  })
}

export function useRulesets(w: string) {
  return useQuery({
    queryKey: keys.rulesets(w),
    queryFn: () => api<RulesetSummary[]>(`${ws(w)}/rulesets`),
  })
}

export function useRuleset(w: string, r: string) {
  return useQuery({ queryKey: keys.ruleset(w, r), queryFn: () => api<RulesetInfo>(rs(w, r)) })
}

export function useDraft(w: string, r: string) {
  return useQuery({
    queryKey: keys.draft(w, r),
    queryFn: () => api<Draft>(`${rs(w, r)}/draft`),
    refetchOnWindowFocus: false,
  })
}

export function useVersions(w: string, r: string) {
  return useQuery({
    queryKey: keys.versions(w, r),
    queryFn: () => api<Version[]>(`${rs(w, r)}/versions`),
    enabled: Boolean(r), // a new sub-rule-set node has no rule set chosen yet
  })
}

export function useTests(w: string, r: string) {
  return useQuery({ queryKey: keys.tests(w, r), queryFn: () => api<TestCase[]>(`${rs(w, r)}/tests`) })
}

// ----------------------------------------------------------------------------- mutations

export function useCreateWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Workspace) => api<Workspace>('/workspaces', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.workspaces }),
  })
}

export function useCreateEntity(w: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { key: string; name: string; description?: string }) =>
      api<Entity>(`${ws(w)}/entities`, { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.entities(w) }),
  })
}

export function useAddSchema(w: string, e: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { schema: JsonSchema } | { samples: unknown[] }) =>
      api<SchemaVersion>(`${ws(w)}/entities/${encodeURIComponent(e)}/schemas`, {
        method: 'POST',
        body,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.schemas(w, e) })
      void qc.invalidateQueries({ queryKey: ['entity', w] }) // "used by" of the referenced ones
      // Versions are immutable, but their `references[].latest` is not: every schema of the
      // workspace may now have a newer version to move to.
      void qc.invalidateQueries({ queryKey: ['schema', w] })
    },
  })
}

export function inferSchema(samples: unknown[], title?: string) {
  return api<JsonSchema>('/schemas/infer', { method: 'POST', body: { samples, title } })
}

export function useCreateRuleset(w: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { key: string; name: string; entity: string; description?: string }) =>
      api<RulesetSummary>(`${ws(w)}/rulesets`, { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.rulesets(w) }),
  })
}

export async function saveDraft(
  w: string,
  r: string,
  graph: RuleGraph,
  lockVersion: number,
  schemaVersion?: number | null,
): Promise<number> {
  const res = await request<{ lockVersion: number }>(`${rs(w, r)}/draft`, {
    method: 'PUT',
    body: { graph, schemaVersion: schemaVersion ?? undefined },
    headers: { 'If-Match': `"${lockVersion}"` },
  })
  return res.data.lockVersion
}

export const validateDraft = (w: string, r: string) =>
  api<Validation>(`${rs(w, r)}/validate`, { method: 'POST' })

export const simulateDraft = (w: string, r: string, input: unknown, options: Record<string, unknown>) =>
  api<ExecutionResult>(`${rs(w, r)}/simulate`, { method: 'POST', body: { input, options } })

export const runTests = (w: string, r: string) =>
  api<TestRun>(`${rs(w, r)}/tests/run`, { method: 'POST' })

export const addTest = (w: string, r: string, test: TestCase) =>
  api<{ name: string }>(`${rs(w, r)}/tests`, { method: 'POST', body: test })

export const deleteTest = (w: string, r: string, name: string) =>
  api<null>(`${rs(w, r)}/tests/${encodeURIComponent(name)}`, { method: 'DELETE' })

export const publish = (
  w: string,
  r: string,
  body: { bump: 'major' | 'minor' | 'patch'; notes?: string; promoteTo?: string },
) => api<Version & { promotedTo?: string; created?: boolean }>(`${rs(w, r)}/publish`, { method: 'POST', body })

export const setAlias = (w: string, r: string, env: string, version: string, effectiveFrom?: string | null) =>
  api<{ env: string; version: string }>(`${rs(w, r)}/aliases/${encodeURIComponent(env)}`, {
    method: 'PUT',
    body: effectiveFrom ? { version, effectiveFrom } : { version },
  })

/** Remove one entry of an environment's schedule (`null`: the undated entry). */
export const deleteAliasEntry = (w: string, r: string, env: string, effectiveFrom: string | null) =>
  api<null>(
    `${rs(w, r)}/aliases/${encodeURIComponent(env)}?effectiveFrom=${encodeURIComponent(effectiveFrom ?? 'always')}`,
    { method: 'DELETE' },
  )

export const fetchDiff = (w: string, r: string, from: string, to = 'draft') =>
  api<GraphDiff>(`${rs(w, r)}/diff?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`)

export const exportBundle = (w: string, r: string, version?: string) =>
  api<Record<string, unknown>>(`${rs(w, r)}/export${version ? `?version=${encodeURIComponent(version)}` : ''}`)

export const importBundle = (w: string, bundle: unknown) =>
  api<ImportResult>(`${ws(w)}/import`, { method: 'POST', body: bundle })

/** Save a JSON document as a file in the browser. */
export function downloadJson(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
