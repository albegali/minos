import { Button, Card, Field, Input, MessageBar, MessageBarBody, Text } from '@fluentui/react-components'
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'

import { BASE } from '../api/client'
import { useServerInfo } from '../api/hooks'

import { useAuth } from '../auth/store'
import { BrandLockup } from '../components/Brand'
import { LanguageSwitch } from '../components/LanguageSwitch'
import { useI18n } from '../i18n'

export function LoginPage() {
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const login = useAuth((s) => s.login)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/w'
  const info = useServerInfo()
  const { t, rich } = useI18n()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`${BASE}/v1/workspaces`, { headers: { Authorization: `Bearer ${key.trim()}` } })
      if (res.status === 404) {
        setError(t('login.noManagement'))
      } else if (!res.ok) {
        setError(t('login.invalidKey'))
      } else {
        login(key.trim())
        navigate(from, { replace: true })
      }
    } catch {
      setError(t('login.unreachable'))
    } finally {
      setBusy(false)
    }
  }

  if (info.data && !info.data.authRequired) return <Navigate to={from} replace />

  return (
    <div className="login">
      <Card className="login-card">
        <div className="login-lang">
          <LanguageSwitch />
        </div>
        <h1 className="login-brand">
          <BrandLockup size={44} />
        </h1>
        <Text>{rich('login.intro', { manage: <code>manage</code>, admin: <code>admin</code> })}</Text>
        <form onSubmit={submit} className="stack">
          <Field label={t('login.apiKey')} required>
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
            {t('login.submit')}
          </Button>
        </form>
        <Text size={200}>
          {rich('login.noDatabase', { demo: <Link to="/demo">{t('login.demoLink')}</Link> })}
        </Text>
      </Card>
    </div>
  )
}
