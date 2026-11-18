import { Button, Card, Field, Input, Link as FluentLink, MessageBar, MessageBarBody, Text } from '@fluentui/react-components'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'

import { ApiError, BASE, errorMessage } from '../api/client'
import { signIn, useServerInfo } from '../api/hooks'
import { useAuth } from '../auth/store'
import { BrandLockup } from '../components/Brand'
import { LanguageSwitch } from '../components/LanguageSwitch'
import { useI18n } from '../i18n'

/** Card layout shared by the pages outside the Studio shell (sign-in, invitation, choice). */
export function AuthCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="login">
      <Card className="login-card">
        <div className="login-lang">
          <LanguageSwitch />
        </div>
        <h1 className="login-brand">
          <BrandLockup size={44} />
        </h1>
        {children}
      </Card>
    </div>
  )
}

function ApiKeyForm({ from }: { from: string }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const login = useAuth((s) => s.login)
  const navigate = useNavigate()
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

  return (
    <form onSubmit={submit} className="stack">
      <Text>{rich('login.intro', { manage: <code>manage</code>, admin: <code>admin</code> })}</Text>
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
  )
}

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [withKey, setWithKey] = useState(false)
  const startSession = useAuth((s) => s.startSession)
  const qc = useQueryClient()
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
      const session = await signIn(email.trim(), password)
      qc.clear() // nothing cached under someone else's credentials
      startSession(session)
      // Several organizations and none chosen: the choice comes first.
      navigate(session.organization ? from : '/organizations', { replace: true, state: { from } })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError(t('login.wrongPassword'))
      else if (err instanceof ApiError && err.status === 429) setError(t('login.tooMany'))
      else if (err instanceof ApiError && err.status === 404) setError(t('login.noManagement'))
      else if (err instanceof ApiError) setError(errorMessage(err))
      else setError(t('login.unreachable'))
    } finally {
      setBusy(false)
    }
  }

  if (info.data && !info.data.authRequired) return <Navigate to={from} replace />

  return (
    <AuthCard>
      {withKey ? (
        <ApiKeyForm from={from} />
      ) : (
        <form onSubmit={submit} className="stack">
          <Text>{t('login.passwordIntro')}</Text>
          <Field label={t('login.email')} required>
            <Input type="email" value={email} onChange={(_, d) => setEmail(d.value)} autoComplete="username" />
          </Field>
          <Field label={t('login.password')} required>
            <Input
              type="password"
              value={password}
              onChange={(_, d) => setPassword(d.value)}
              autoComplete="current-password"
            />
          </Field>
          {error && (
            <MessageBar intent="error">
              <MessageBarBody>{error}</MessageBarBody>
            </MessageBar>
          )}
          <Button appearance="primary" type="submit" disabled={busy || !email.trim() || !password}>
            {t('login.submit')}
          </Button>
        </form>
      )}
      <FluentLink as="button" onClick={() => setWithKey(!withKey)}>
        {withKey ? t('login.usePassword') : t('login.useApiKey')}
      </FluentLink>
      <Text size={200}>{rich('login.noDatabase', { demo: <Link to="/demo">{t('login.demoLink')}</Link> })}</Text>
    </AuthCard>
  )
}
