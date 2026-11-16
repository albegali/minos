import './styles.css'

import { FluentProvider, webDarkTheme, webLightTheme } from '@fluentui/react-components'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'

import { ApiError } from './api/client'
import { RequireAuth, Shell } from './components/Shell'
import { EditorPage } from './editor/EditorPage'
import { DemoPage } from './pages/DemoPage'
import { EntityPage } from './pages/EntityPage'
import { LoginPage } from './pages/LoginPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { WorkspacesPage } from './pages/WorkspacesPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
})

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/demo', element: <DemoPage /> },
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
      { path: '/w/:ws/entities/:entity', element: <EntityPage /> },
      { path: '/w/:ws/rulesets/:rs', element: <EditorPage /> },
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
