// Minimal typed client for the Management and Execution APIs.

import { useAuth } from '../auth/store'
import { translateApiText } from '../i18n/api'

export interface Problem {
  status: number
  title: string
  detail: string
  [key: string]: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly problem: Problem

  constructor(problem: Problem) {
    super(problem.detail || problem.title)
    this.status = problem.status
    this.problem = problem
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
}

export interface ApiResponse<T> {
  data: T
  headers: Headers
}

const BASE = (import.meta.env.VITE_MINOS_API as string | undefined) ?? ''

export async function request<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
  const key = useAuth.getState().apiKey
  const headers: Record<string, string> = { ...options.headers }
  if (key) headers.Authorization = `Bearer ${key}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(`${BASE}/v1${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  const text = await res.text()
  const body: unknown = text ? JSON.parse(text) : null
  if (!res.ok) {
    const problem =
      body && typeof body === 'object' && 'status' in body
        ? (body as Problem)
        : { status: res.status, title: res.statusText, detail: text || res.statusText }
    if (res.status === 401) useAuth.getState().logout()
    throw new ApiError(problem)
  }
  return { data: body as T, headers: res.headers }
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return (await request<T>(path, options)).data
}

/**
 * Human-readable message for any error thrown by the client or by fetch, in the Studio
 * language when the backend message is a known one.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return translateApiText(error.problem.detail || error.message)
  if (error instanceof Error) return error.message
  return String(error)
}
