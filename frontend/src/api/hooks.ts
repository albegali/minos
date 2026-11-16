// TanStack Query hooks over the Management API.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { RuleGraph } from '../rgd'
import { api, request } from './client'
import type {
  Catalog,
  Draft,
  Entity,
  ExecutionResult,
  JsonSchema,
  RulesetInfo,
  RulesetSummary,
  SchemaVersion,
  TestCase,
  TestRun,
  Validation,
  Version,
  Workspace,
} from './types'

const ws = (slug: string) => `/workspaces/${encodeURIComponent(slug)}`
const rs = (slug: string, key: string) => `${ws(slug)}/rulesets/${encodeURIComponent(key)}`

export const keys = {
  info: ['info'] as const,
  workspaces: ['workspaces'] as const,
  catalog: ['catalog'] as const,
  entities: (w: string) => ['entities', w] as const,
  schemas: (w: string, e: string) => ['schemas', w, e] as const,
  schema: (w: string, e: string, v: number) => ['schema', w, e, v] as const,
  rulesets: (w: string) => ['rulesets', w] as const,
  ruleset: (w: string, r: string) => ['ruleset', w, r] as const,
  draft: (w: string, r: string) => ['draft', w, r] as const,
  versions: (w: string, r: string) => ['versions', w, r] as const,
  tests: (w: string, r: string) => ['tests', w, r] as const,
}

export interface ServerInfo {
  name: string
  version: string
  authRequired: boolean
  management: boolean
  database: boolean
}

/** Public description of the installation: does it need API keys, has it a database? */
export function useServerInfo() {
  return useQuery({ queryKey: keys.info, queryFn: () => api<ServerInfo>('/info'), staleTime: Infinity })
}

export function useWorkspaces() {
  return useQuery({ queryKey: keys.workspaces, queryFn: () => api<Workspace[]>('/workspaces') })
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

export function useSchemas(w: string, e: string) {
  return useQuery({
    queryKey: keys.schemas(w, e),
    queryFn: () => api<SchemaVersion[]>(`${ws(w)}/entities/${encodeURIComponent(e)}/schemas`),
  })
}

export function useSchema(w: string, e: string, v: number | null | undefined) {
  return useQuery({
    queryKey: keys.schema(w, e, v ?? 0),
    queryFn: () => api<SchemaVersion>(`${ws(w)}/entities/${encodeURIComponent(e)}/schemas/${v}`),
    enabled: Boolean(v),
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
  return useQuery({ queryKey: keys.versions(w, r), queryFn: () => api<Version[]>(`${rs(w, r)}/versions`) })
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
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.schemas(w, e) }),
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
) => api<Version & { promotedTo?: string }>(`${rs(w, r)}/publish`, { method: 'POST', body })

export const setAlias = (w: string, r: string, env: string, version: string) =>
  api<{ env: string; version: string }>(`${rs(w, r)}/aliases/${encodeURIComponent(env)}`, {
    method: 'PUT',
    body: { version },
  })
