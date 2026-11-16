import './styles.css'

import { FluentProvider, Spinner, webDarkTheme, webLightTheme } from '@fluentui/react-components'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, type ReactNode, StrictMode, Suspense, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'

import { ApiError } from './api/client'
import { RequireAuth, Shell } from './components/Shell'
import { LoginPage } from './pages/LoginPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { WorkspacesPage } from './pages/WorkspacesPage'

// Heavy pages (React Flow canvas, editors) load on demand.
const EditorPage = lazy(() => import('./editor/EditorPage').then((m) => ({ default: m.EditorPage })))
const EntityPage = lazy(() => import('./pages/EntityPage').then((m) => ({ default: m.EntityPage })))
const DemoPage = lazy(() => import('./pages/DemoPage').then((m) => ({ default: m.DemoPage })))

const page = (element: ReactNode) => (
  <Suspense fallback={<Spinner label="Caricamento…" className="centered" />}>{element}</Suspense>
)

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
})

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
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
    <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
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
