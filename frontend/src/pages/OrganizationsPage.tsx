import { Button, Card, CardHeader, Spinner, Text } from '@fluentui/react-components'
import { Building20Regular } from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'

import { chooseOrganization, signOut } from '../api/hooks'
import type { Organization } from '../api/types'
import { isSession, useAuth } from '../auth/store'
import { ErrorBar } from '../components/forms'
import { useI18n } from '../i18n'
import { AuthCard } from './LoginPage'

/** Moves the session to an organization; clears what was cached for the previous one. */
export function useSwitchOrganization() {
  const updateSession = useAuth((s) => s.updateSession)
  const qc = useQueryClient()
  return async (slug: string) => {
    const info = await chooseOrganization(slug)
    qc.clear()
    updateSession(info)
    return info
  }
}

export function RoleLabel({ role }: { role?: string }) {
  const { t } = useI18n()
  if (!role) return null
  return <>{t(`roles.${role}` as 'roles.owner')}</>
}

/** Choice of the organization after signing in with an address that belongs to several. */
export function OrganizationsPage() {
  const token = useAuth((s) => s.token)
  const session = useAuth((s) => s.session)
  const logout = useAuth((s) => s.logout)
  const switchTo = useSwitchOrganization()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/w'
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const { t } = useI18n()

  if (!token || !isSession(token) || !session) return <Navigate to="/login" replace />

  async function choose(o: Organization) {
    setBusy(o.slug)
    setError(null)
    try {
      await switchTo(o.slug)
      navigate(from === '/organizations' ? '/w' : from, { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <AuthCard>
      <Text weight="semibold">{t('orgs.hello', { name: session.user.name })}</Text>
      {session.organizations.length === 0 ? (
        <Text>{t('orgs.none')}</Text>
      ) : (
        <>
          <Text>{t('orgs.choose')}</Text>
          <div className="stack">
            {session.organizations.map((o) => (
              <Card
                key={o.slug}
                className="clickable"
                onClick={() => void choose(o)}
                aria-current={session.organization?.slug === o.slug}
              >
                <CardHeader
                  image={busy === o.slug ? <Spinner size="tiny" /> : <Building20Regular />}
                  header={<Text weight="semibold">{o.name}</Text>}
                  description={
                    <Text size={200}>
                      {o.slug} · <RoleLabel role={o.role} />
                    </Text>
                  }
                />
              </Card>
            ))}
          </div>
        </>
      )}
      <ErrorBar error={error} />
      <Button
        appearance="subtle"
        onClick={async () => {
          await signOut().catch(() => undefined)
          logout()
          navigate('/login', { replace: true })
        }}
      >
        {t('shell.signOut')}
      </Button>
    </AuthCard>
  )
}
