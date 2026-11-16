// Creates the starting point a business user would be given: a workspace and a key with the
// `manage` scope (no admin rights). Everything else in the tests happens through the UI.

import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
export const STATE = join(here, '.state.json')
const API = 'http://127.0.0.1:8000/v1'

export default async function globalSetup() {
  const url = process.env.MINOS_E2E_DATABASE_URL ?? 'postgresql+asyncpg://minos:minos@localhost:5432/minos_e2e'
  const out = execFileSync('uv', ['run', 'python', '-m', 'minos.cli', 'create-admin-key', '--name', 'e2e-admin'], {
    cwd: join(here, '..', '..', 'backend'),
    env: { ...process.env, MINOS_DATABASE_URL: url },
    encoding: 'utf8',
  })
  const admin = out.trim().split('\n').at(-1) as string
  const headers = { Authorization: `Bearer ${admin}`, 'Content-Type': 'application/json' }
  const ws = await fetch(`${API}/workspaces`, { method: 'POST', headers, body: JSON.stringify({ slug: 'aurora', name: 'Aurora Business School' }) })
  if (!ws.ok) throw new Error(`workspace: ${ws.status} ${await ws.text()}`)
  const key = await fetch(`${API}/workspaces/aurora/api-keys`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: 'ufficio-didattica', scopes: ['manage'] }),
  })
  if (!key.ok) throw new Error(`key: ${key.status} ${await key.text()}`)
  const exec = await fetch(`${API}/workspaces/aurora/api-keys`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: 'dynamics', scopes: ['exec'] }),
  })
  const manage = (await key.json()) as { key: string }
  const execution = (await exec.json()) as { key: string }
  writeFileSync(STATE, JSON.stringify({ manageKey: manage.key, execKey: execution.key }))
}
