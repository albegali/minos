// Creates the starting point of the scenario: a workspace. On an open installation (the
// default) the management API needs no key.

const API = 'http://127.0.0.1:8000/v1'

export default async function globalSetup() {
  const res = await fetch(`${API}/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slug: 'aurora', name: 'Aurora Business School' }),
  })
  if (!res.ok) throw new Error(`workspace: ${res.status} ${await res.text()}`)
}
