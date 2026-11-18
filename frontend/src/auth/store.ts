// Credentials of the current tab: a session token (sign-in with e-mail and password) or an
// API key, plus, for a session, who is signed in and in which organization. Kept in
// sessionStorage so a reload keeps the user signed in while closing the tab forgets it.
// Storage can be unavailable (private mode, blocked site data): every access is guarded and
// the app still works for the session.

import { create } from 'zustand'

import type { SessionInfo } from '../api/types'

const TOKEN_KEY = 'minos.apiKey'
const SESSION_KEY = 'minos.session'
const ORG_KEY = 'minos.organization'

function read(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, value)
  } catch {
    // ignore: the value lives in memory for this tab
  }
}

function readSession(): SessionInfo | null {
  const raw = read(SESSION_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as SessionInfo
  } catch {
    return null
  }
}

interface AuthState {
  /** Sent as `Authorization: Bearer`: a session token (`mss_…`) or an API key (`mns_…`). */
  token: string | null
  /** Set for a sign-in with e-mail and password; null with an API key. */
  session: SessionInfo | null
  /** Sign in with an API key. */
  login: (key: string) => void
  /** Start a session (sign-in, accepted invitation): `info.token` is required. */
  startSession: (info: SessionInfo & { token: string }) => void
  /** New details of the current session (e.g. another organization chosen). */
  updateSession: (info: SessionInfo) => void
  logout: () => void
  /**
   * Organization the Studio works in without a session (open installation, admin key): sent
   * as `X-Minos-Organization`. Workspace slugs are unique only within an organization.
   */
  organization: string
  setOrganization: (slug: string) => void
}

export const useAuth = create<AuthState>((set) => ({
  token: read(TOKEN_KEY),
  session: readSession(),
  login: (key) => {
    write(TOKEN_KEY, key)
    write(SESSION_KEY, null)
    set({ token: key, session: null })
  },
  startSession: ({ token, ...info }) => {
    write(TOKEN_KEY, token)
    write(SESSION_KEY, JSON.stringify(info))
    set({ token, session: info })
  },
  updateSession: ({ user, organization, organizations, expiresAt }) => {
    const info = { user, organization, organizations, expiresAt }
    write(SESSION_KEY, JSON.stringify(info))
    set({ session: info })
  },
  logout: () => {
    write(TOKEN_KEY, null)
    write(SESSION_KEY, null)
    set({ token: null, session: null })
  },
  organization: read(ORG_KEY) ?? 'default',
  setOrganization: (slug) => {
    write(ORG_KEY, slug)
    set({ organization: slug })
  },
}))

/** Whether the token is a sign-in session (and not an API key). */
export const isSession = (token: string | null) => Boolean(token?.startsWith('mss_'))
