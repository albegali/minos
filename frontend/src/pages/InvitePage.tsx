import { Button, Field, Input, Spinner, Text } from '@fluentui/react-components'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { acceptInvitation, fetchInvitation, signOut } from '../api/hooks'
import { isSession, useAuth } from '../auth/store'
import { ErrorBar } from '../components/forms'
import { useI18n } from '../i18n'
import { AuthCard } from './LoginPage'
import { RoleLabel } from './OrganizationsPage'

/**
 * Invitation link (`/invite/<token>`). Signed in: the invited address joins the current
 * account, which can then sign in with it too. Otherwise: the password of the account that
 * already uses the address, or a new account.
 */
export function InvitePage() {
  const token = useParams().token as string
  const preview = useQuery({ queryKey: ['invitation', token], queryFn: () => fetchInvitation(token), retry: false })
  const auth = useAuth()
  const signedIn = isSession(auth.token) && auth.session !== null
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const { t } = useI18n()

  if (preview.isLoading) return <Spinner className="centered" />
  if (preview.error || !preview.data) {
    return (
      <AuthCard>
        <ErrorBar error={preview.error ?? new Error('?')} />
        <Link to="/login">{t('invite.toLogin')}</Link>
      </AuthCard>
    )
  }
  const inv = preview.data
  const newAccount = !signedIn && !inv.accountExists
  const mismatch = newAccount && password !== '' && confirm !== '' && password !== confirm

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = signedIn ? {} : newAccount ? { name: name.trim(), password } : { password }
      const session = await acceptInvitation(token, body)
      qc.clear()
      auth.startSession(session)
      navigate('/w', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? new Error(t('login.wrongPassword')) : err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard>
      <Text>
        {t('invite.intro', { org: inv.organization.name, by: inv.invitedBy.replace(/^user:/, '') })}{' '}
        (<RoleLabel role={inv.role} />)
      </Text>
      <form onSubmit={submit} className="stack">
        {signedIn ? (
          <Text>
            {t('invite.asSignedIn', { email: inv.email, account: auth.session?.user.email ?? '' })}
          </Text>
        ) : (
          <>
            <Field label={t('login.email')}>
              <Input value={inv.email} readOnly />
            </Field>
            {newAccount && (
              <Field label={t('invite.name')} required>
                <Input value={name} onChange={(_, d) => setName(d.value)} autoComplete="name" />
              </Field>
            )}
            <Field
              label={t('login.password')}
              required
              hint={newAccount ? t('invite.passwordHint') : t('invite.existingAccount')}
            >
              <Input
                type="password"
                value={password}
                onChange={(_, d) => setPassword(d.value)}
                autoComplete={newAccount ? 'new-password' : 'current-password'}
              />
            </Field>
            {newAccount && (
              <Field
                label={t('invite.confirm')}
                required
                validationMessage={mismatch ? t('invite.mismatch') : undefined}
              >
                <Input
                  type="password"
                  value={confirm}
                  onChange={(_, d) => setConfirm(d.value)}
                  autoComplete="new-password"
                />
              </Field>
            )}
          </>
        )}
        <ErrorBar error={error} />
        <Button
          appearance="primary"
          type="submit"
          disabled={
            busy || (!signedIn && !password) || (newAccount && (!name.trim() || password !== confirm))
          }
        >
          {t('invite.accept')}
        </Button>
      </form>
      {signedIn ? (
        <Button
          appearance="subtle"
          onClick={async () => {
            await signOut().catch(() => undefined)
            auth.logout()
            qc.clear()
          }}
        >
          {t('invite.otherAccount')}
        </Button>
      ) : (
        <Text size={200}>
          {t('invite.haveAccount')} <Link to="/login" state={{ from: `/invite/${token}` }}>{t('invite.signInFirst')}</Link>
        </Text>
      )}
    </AuthCard>
  )
}
