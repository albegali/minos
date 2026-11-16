import {
  Breadcrumb,
  BreadcrumbButton,
  BreadcrumbDivider,
  BreadcrumbItem,
  Button,
  Spinner,
  Text,
} from '@fluentui/react-components'
import { SignOut20Regular } from '@fluentui/react-icons'
import { Fragment, type ReactNode } from 'react'
import { Link, Navigate, Outlet, useLocation, useNavigate, useParams } from 'react-router'

import { useServerInfo } from '../api/hooks'
import { useAuth } from '../auth/store'
import { BrandLockup } from './Brand'
import { ErrorBar } from './forms'

/**
 * Gate for the Studio pages. Open installations (the default) need no key; installations
 * without a database have no management API, so the Studio falls back to the demo.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const apiKey = useAuth((s) => s.apiKey)
  const location = useLocation()
  const info = useServerInfo()
  if (info.isLoading) return <Spinner label="Connessione all'API…" className="centered" />
  if (info.error) return <ErrorBar error={info.error} />
  if (info.data && !info.data.management) return <Navigate to="/demo" replace />
  if (info.data?.authRequired && !apiKey) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

function Crumbs() {
  const { ws, entity, rs } = useParams()
  const navigate = useNavigate()
  const items: { label: string; to: string }[] = [{ label: 'Workspace', to: '/w' }]
  if (ws) items.push({ label: ws, to: `/w/${ws}` })
  if (ws && entity) items.push({ label: `Entità ${entity}`, to: `/w/${ws}/entities/${entity}` })
  if (ws && rs) items.push({ label: `Rule set ${rs}`, to: `/w/${ws}/rulesets/${rs}` })
  return (
    <Breadcrumb aria-label="Percorso">
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

export function Shell() {
  const logout = useAuth((s) => s.logout)
  const info = useServerInfo()
  return (
    <div className="shell">
      <header className="shell-header">
        <Link to="/w" className="brand-link" aria-label="Minos Studio, torna ai workspace">
          <BrandLockup />
        </Link>
        <span className="shell-divider" aria-hidden="true" />
        <Crumbs />
        {info.data?.authRequired && (
          <Button appearance="subtle" icon={<SignOut20Regular />} onClick={logout}>
            Esci
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
