import {
  Breadcrumb,
  BreadcrumbButton,
  BreadcrumbDivider,
  BreadcrumbItem,
  Button,
  Menu,
  MenuDivider,
  MenuGroup,
  MenuGroupHeader,
  MenuItem,
  MenuItemRadio,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Spinner,
  Text,
} from '@fluentui/react-components'
import { Building20Regular, People20Regular, Person20Regular, SignOut20Regular } from '@fluentui/react-icons'
import { useQueryClient } from '@tanstack/react-query'
import { Fragment, type ReactNode, useState } from 'react'
import { Link, Navigate, Outlet, useLocation, useNavigate, useParams } from 'react-router'

import { signOut, useServerInfo } from '../api/hooks'
import { isSession, useAuth } from '../auth/store'
import { useSwitchOrganization } from '../pages/OrganizationsPage'
import { useI18n } from '../i18n'
import { BrandLockup } from './Brand'
import { ErrorBar } from './forms'
import { LanguageSwitch } from './LanguageSwitch'

/**
 * Gate for the Studio pages. Open installations (the default) need no key; installations
 * without a database have no management API, so the Studio falls back to the demo.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const apiKey = useAuth((s) => s.token)
  const session = useAuth((s) => s.session)
  const location = useLocation()
  const info = useServerInfo()
  const { t } = useI18n()
  if (info.isLoading) return <Spinner label={t('shell.connecting')} className="centered" />
  if (info.error) return <ErrorBar error={info.error} />
  if (info.data && !info.data.management) return <Navigate to="/demo" replace />
  if (info.data?.authRequired && !apiKey) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (info.data?.authRequired && isSession(apiKey) && !session?.organization) {
    // signed in with an address of several organizations: choose one first
    return <Navigate to="/organizations" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

function Crumbs() {
  const { ws, entity, rs } = useParams()
  const navigate = useNavigate()
  const { t } = useI18n()
  const items: { label: string; to: string }[] = [{ label: t('shell.workspaces'), to: '/w' }]
  if (ws) items.push({ label: ws, to: `/w/${ws}` })
  if (ws && entity) items.push({ label: t('shell.entityCrumb', { key: entity }), to: `/w/${ws}/entities/${entity}` })
  if (ws && rs) items.push({ label: t('shell.rulesetCrumb', { key: rs }), to: `/w/${ws}/rulesets/${rs}` })
  return (
    <Breadcrumb aria-label={t('shell.breadcrumb')}>
      {items.map((item, i) => (
        <Fragment key={item.to}>
          <BreadcrumbItem>
            <BreadcrumbButton current={i === items.length - 1} onClick={() => navigate(item.to)}>
              {item.label}
            </BreadcrumbButton>
          </BreadcrumbItem>
          {i < items.length - 1 && <BreadcrumbDivider />}
        </Fragment>
      ))}
    </Breadcrumb>
  )
}

/** Organization switcher and user menu of a signed-in session. */
function AccountMenu() {
  const session = useAuth((s) => s.session)
  const logout = useAuth((s) => s.logout)
  const switchTo = useSwitchOrganization()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const { t } = useI18n()
  if (!session) return null
  const current = session.organization?.slug ?? ''
  return (
    <>
      <Menu
        checkedValues={{ org: [current] }}
        onCheckedValueChange={async (_, d) => {
          const slug = d.checkedItems[0]
          if (!slug || slug === current) return
          setError(null)
          try {
            await switchTo(slug)
            navigate('/w')
          } catch (err) {
            setError(err)
          }
        }}
      >
        <MenuTrigger disableButtonEnhancement>
          <Button appearance="subtle" icon={<Building20Regular />} title={t('shell.organization')}>
            {session.organization?.name ?? t('shell.noOrganization')}
          </Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuGroup>
              <MenuGroupHeader>{t('shell.organizations')}</MenuGroupHeader>
              {session.organizations.map((o) => (
                <MenuItemRadio key={o.slug} name="org" value={o.slug}>
                  {o.name}
                </MenuItemRadio>
              ))}
            </MenuGroup>
            <MenuDivider />
            <MenuItem icon={<People20Regular />} onClick={() => navigate('/members')}>
              {t('shell.members')}
            </MenuItem>
          </MenuList>
        </MenuPopover>
      </Menu>
      <Menu>
        <MenuTrigger disableButtonEnhancement>
          <Button appearance="subtle" icon={<Person20Regular />} title={t('shell.account')}>
            {session.user.name}
          </Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuGroup>
              <MenuGroupHeader>{session.user.emails.join(', ')}</MenuGroupHeader>
            </MenuGroup>
            <MenuItem
              icon={<SignOut20Regular />}
              onClick={async () => {
                await signOut().catch(() => undefined)
                logout()
                qc.clear()
              }}
            >
              {t('shell.signOut')}
            </MenuItem>
          </MenuList>
        </MenuPopover>
      </Menu>
      {error !== null && <ErrorBar error={error} />}
    </>
  )
}

export function Shell() {
  const logout = useAuth((s) => s.logout)
  const token = useAuth((s) => s.token)
  const info = useServerInfo()
  const { t } = useI18n()
  return (
    <div className="shell">
      <header className="shell-header">
        <Link to="/w" className="brand-link" aria-label={t('shell.home')}>
          <BrandLockup />
        </Link>
        <span className="shell-divider" aria-hidden="true" />
        <Crumbs />
        <LanguageSwitch />
        {info.data?.authRequired && isSession(token) && <AccountMenu />}
        {info.data?.authRequired && !isSession(token) && (
          <Button appearance="subtle" icon={<SignOut20Regular />} onClick={logout}>
            {t('shell.signOut')}
          </Button>
        )}
      </header>
      <main className="shell-main">
        <Outlet />
      </main>
    </div>
  )
}

/** A centred, readable column for list and form pages. */
export function Page({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <div className="page-head">
        <Text as="h1" size={700} weight="bold">
          {title}
        </Text>
        <div className="page-actions">{actions}</div>
      </div>
      {children}
    </div>
  )
}
