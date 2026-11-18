import './styles.css'

import { FluentProvider, Spinner } from '@fluentui/react-components'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, type ReactNode, StrictMode, Suspense, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'

import { ApiError } from './api/client'
import { RequireAuth, Shell } from './components/Shell'
import { InvitePage } from './pages/InvitePage'
import { LoginPage } from './pages/LoginPage'
import { MembersPage } from './pages/MembersPage'
import { OrganizationsPage } from './pages/OrganizationsPage'
import { SignupPage } from './pages/SignupPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { WorkspacesPage } from './pages/WorkspacesPage'
import { useI18n } from './i18n'
import { minosDark, minosLight } from './theme'

// Heavy pages (React Flow canvas, editors) load on demand.
const EditorPage = lazy(() => import('./editor/EditorPage').then((m) => ({ default: m.EditorPage })))
const EntityPage = lazy(() => import('./pages/EntityPage').then((m) => ({ default: m.EntityPage })))
const DemoPage = lazy(() => import('./pages/DemoPage').then((m) => ({ default: m.DemoPage })))

function Loading() {
  const { t } = useI18n()
  return <Spinner label={t('common.loading')} className="centered" />
}

const page = (element: ReactNode) => <Suspense fallback={<Loading />}>{element}</Suspense>

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
})

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/organizations', element: <OrganizationsPage /> },
  { path: '/signup', element: <SignupPage /> },
  { path: '/invite/:token', element: <InvitePage /> },
  { path: '/demo', element: page(<DemoPage />) },
  {
    element: (
      <RequireAuth>
        <Shell />
      </RequireAuth>
    ),
    children: [
      { path: '/', element: <Navigate to="/w" replace /> },
      { path: '/w', element: <WorkspacesPage /> },
      { path: '/members', element: <MembersPage /> },
      { path: '/w/:ws', element: <WorkspacePage /> },
      { path: '/w/:ws/entities/:entity', element: page(<EntityPage />) },
      { path: '/w/:ws/rulesets/:rs', element: page(<EditorPage />) },
    ],
  },
])

function usePrefersDark(): boolean {
  const query = '(prefers-color-scheme: dark)'
  const [dark, setDark] = useState(() => window.matchMedia?.(query).matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.(query)
    if (!mq) return
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return dark
}

function Root() {
  const dark = usePrefersDark()
  return (
    <FluentProvider theme={dark ? minosDark : minosLight}>
      {/* Not on FluentProvider itself: Fluent copies its className onto portal hosts
          (dialogs, menus), and a full-page background there would cover them. */}
      <div className="fluent-root">
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </div>
    </FluentProvider>
  )
}

const root = document.getElementById('root')
if (!root) throw new Error('missing #root element')

createRoot(root).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
