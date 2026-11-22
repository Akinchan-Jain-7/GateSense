import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useState, type ReactNode } from 'react'
import { createBrowserRouter, Outlet, RouterProvider, type RouteObject } from 'react-router'
import { Toaster } from 'sonner'

import { ApiError } from '@/lib/api/client'
import { AuthProvider, RequireRole, useAuth } from '@/lib/auth'
import { LiveProvider } from '@/lib/live'
import { ThemeProvider, useTheme } from '@/lib/theme'

import { FullPageLoader, NotFound, RouteError } from './fallbacks'

// Each area is its own bundle: a resident on a phone never downloads the admin charts.
const Landing = lazy(() => import('@/features/landing/Landing'))
const Login = lazy(() => import('@/features/auth/Login'))
const GuardConsole = lazy(() => import('@/features/guard/GuardConsole'))
const ResidentApp = lazy(() => import('@/features/resident/ResidentApp'))
const AdminApp = lazy(() => import('@/features/admin/AdminApp'))

function Area({ children }: { children: ReactNode }) {
  return <Suspense fallback={<FullPageLoader />}>{children}</Suspense>
}

function Shell() {
  const { user } = useAuth()
  const { resolved } = useTheme()
  return (
    <LiveProvider enabled={user !== null}>
      <Outlet />
      <Toaster theme={resolved} position="top-center" closeButton richColors={false} />
    </LiveProvider>
  )
}

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      {
        path: '/',
        element: (
          <Area>
            <Landing />
          </Area>
        ),
      },
      {
        path: '/login',
        element: (
          <Area>
            <Login />
          </Area>
        ),
      },
      {
        path: '/guard/*',
        element: (
          <RequireRole role="guard" fallback={<FullPageLoader />}>
            <Area>
              <GuardConsole />
            </Area>
          </RequireRole>
        ),
      },
      {
        path: '/resident/*',
        element: (
          <RequireRole role="resident" fallback={<FullPageLoader />}>
            <Area>
              <ResidentApp />
            </Area>
          </RequireRole>
        ),
      },
      {
        path: '/admin/*',
        element: (
          <RequireRole role="admin" fallback={<FullPageLoader />}>
            <Area>
              <AdminApp />
            </Area>
          </RequireRole>
        ),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Don't hammer the API on a 4xx: it won't fix itself.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 2,
        refetchOnWindowFocus: true,
      },
    },
  })
}

export function Providers({ client, children }: { client: QueryClient; children: ReactNode }) {
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <AuthProvider>{children}</AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

export function App() {
  const [client] = useState(makeQueryClient)
  const [router] = useState(() => createBrowserRouter(routes))
  return (
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>
  )
}
