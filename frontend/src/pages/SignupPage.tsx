import { Button, Field, Input, Text } from '@fluentui/react-components'
import { useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import { signUp, useServerInfo } from '../api/hooks'
import { isSession, useAuth } from '../auth/store'
import { ErrorBar, slugify } from '../components/forms'
import { useI18n } from '../i18n'
import { AuthCard } from './LoginPage'

/**
 * Registration of a new organization, whose owner is the person registering it: the signed-in
 * account, the account that already uses the address (with its password), or a new one.
 * Shown only when the installation allows it (MINOS_ALLOW_SIGNUP).
 */
export function SignupPage() {
  const info = useServerInfo()
  const auth = useAuth()
  const signedIn = isSession(auth.token) && auth.session !== null
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [orgName, setOrgName] = useState('')
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const { t } = useI18n()

  if (info.data && !info.data.signup) return <Navigate to="/login" replace />

  const mismatch = password !== '' && confirm !== '' && password !== confirm
  const ready =
    orgName.trim() && slug && (signedIn || (name.trim() && email.trim() && password && password === confirm))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const organization = { slug, name: orgName.trim() }
      const session = await signUp(
        signedIn ? { organization } : { organization, name: name.trim(), email: email.trim(), password },
      )
      qc.clear()
      auth.startSession(session)
      navigate('/w', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? new Error(t('signup.existingAccount')) : err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard>
      <Text weight="semibold">{t('signup.title')}</Text>
      <Text>{signedIn ? t('signup.introSignedIn', { email: auth.session?.user.email ?? '' }) : t('signup.intro')}</Text>
      <form onSubmit={submit} className="stack">
        <Field label={t('signup.orgName')} required>
          <Input
            value={orgName}
            onChange={(_, d) => {
              setOrgName(d.value)
              setSlug(slugify(d.value))
            }}
            autoComplete="organization"
          />
        </Field>
        <Field label={t('workspaces.slug')} hint={t('signup.slugHint')} required>
          <Input value={slug} onChange={(_, d) => setSlug(d.value)} />
        </Field>
        {!signedIn && (
          <>
            <Field label={t('invite.name')} required>
              <Input value={name} onChange={(_, d) => setName(d.value)} autoComplete="name" />
            </Field>
            <Field label={t('login.email')} required>
              <Input type="email" value={email} onChange={(_, d) => setEmail(d.value)} autoComplete="username" />
            </Field>
            <Field label={t('login.password')} required hint={t('signup.passwordHint')}>
              <Input
                type="password"
                value={password}
                onChange={(_, d) => setPassword(d.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field label={t('invite.confirm')} required validationMessage={mismatch ? t('invite.mismatch') : undefined}>
              <Input type="password" value={confirm} onChange={(_, d) => setConfirm(d.value)} autoComplete="new-password" />
            </Field>
          </>
        )}
        <ErrorBar error={error} />
        <Button appearance="primary" type="submit" disabled={busy || !ready}>
          {t('signup.submit')}
        </Button>
      </form>
      <Text size={200}>
        {signedIn ? <Link to="/w">{t('signup.back')}</Link> : <Link to="/login">{t('signup.haveAccount')}</Link>}
      </Text>
    </AuthCard>
  )
}
