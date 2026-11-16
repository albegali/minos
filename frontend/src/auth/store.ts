// API key of the current session. Kept in sessionStorage so a reload keeps the user signed
// in while closing the tab forgets the key. Storage can be unavailable (private mode,
// blocked site data): every access is guarded and the app still works for the session.

import { create } from 'zustand'

const STORAGE_KEY = 'minos.apiKey'

function read(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function write(value: string | null): void {
  try {
    if (value === null) sessionStorage.removeItem(STORAGE_KEY)
    else sessionStorage.setItem(STORAGE_KEY, value)
  } catch {
    // ignore: the key lives in memory for this session
  }
}

interface AuthState {
  apiKey: string | null
  login: (key: string) => void
  logout: () => void
}

export const useAuth = create<AuthState>((set) => ({
  apiKey: read(),
  login: (key) => {
    write(key)
    set({ apiKey: key })
  },
  logout: () => {
    write(null)
    set({ apiKey: null })
  },
}))
