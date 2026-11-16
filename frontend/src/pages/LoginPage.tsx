import { Button, Card, Field, Input, MessageBar, MessageBarBody, Text } from '@fluentui/react-components'
import { type FormEvent, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { useAuth } from '../auth/store'

export function LoginPage() {
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const login = useAuth((s) => s.login)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/w'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await fetch('/v1/workspaces', { headers: { Authorization: `Bearer ${key.trim()}` } })
      if (res.status === 404) {
        setError('Questa installazione non ha la Management API (manca il database): usa la demo.')
      } else if (!res.ok) {
        setError('Chiave non valida o revocata.')
      } else {
        login(key.trim())
        navigate(from, { replace: true })
      }
    } catch {
      setError('API non raggiungibile.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <Card className="login-card">
        <Text as="h1" size={600} weight="semibold">
          Minos Studio
        </Text>
        <Text>Accedi con una API key con scope <code>manage</code> o <code>admin</code>.</Text>
        <form onSubmit={submit} className="stack">
          <Field label="API key" required>
            <Input
              type="password"
              value={key}
              onChange={(_, d) => setKey(d.value)}
              placeholder="mns_…"
              autoComplete="off"
            />
          </Field>
          {error && (
            <MessageBar intent="error">
              <MessageBarBody>{error}</MessageBarBody>
            </MessageBar>
          )}
          <Button appearance="primary" type="submit" disabled={busy || !key.trim()}>
            Accedi
          </Button>
        </form>
        <Text size={200}>
          Senza database? Apri la <Link to="/demo">demo</Link> con gli esempi Aurora.
        </Text>
      </Card>
    </div>
  )
}
