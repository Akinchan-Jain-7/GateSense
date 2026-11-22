import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { homeFor, signIn, signOut, type Role } from './api/auth'
import { api, unwrap, type Schemas } from './api/client'
import { getTokens, onTokensChange } from './api/tokens'

export type CurrentUser = Schemas['CurrentUserResponse']

interface AuthState {
  user: CurrentUser | null
  status: 'anonymous' | 'loading' | 'ready'
  signIn: (email: string, password: string) => Promise<CurrentUser>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [signedIn, setSignedIn] = useState(() => getTokens() !== null)

  useEffect(
    () =>
      onTokensChange((tokens) => {
        setSignedIn(tokens !== null)
        if (!tokens) queryClient.clear()
      }),
    [queryClient],
  )

  const me = useQuery({
    queryKey: ['me'],
    queryFn: () => unwrap(api.GET('/api/v1/me')),
    enabled: signedIn,
    staleTime: 5 * 60_000,
  })

  const value = useMemo<AuthState>(
    () => ({
      user: signedIn ? (me.data ?? null) : null,
      status: !signedIn ? 'anonymous' : me.data ? 'ready' : me.isError ? 'anonymous' : 'loading',
      signIn: async (email, password) => {
        queryClient.clear()
        await signIn(email, password)
        return queryClient.query({
          queryKey: ['me'],
          queryFn: () => unwrap(api.GET('/api/v1/me')),
        })
      },
      signOut: async () => {
        await signOut()
        queryClient.clear()
      },
    }),
    [signedIn, me.data, me.isError, queryClient],
  )
  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}

/** Guard a route: signed-out people go to /login, the wrong role goes to its own home. */
export function RequireRole({
  role,
  children,
  fallback,
}: {
  role: Role
  children: ReactNode
  fallback: ReactNode
}) {
  const { user, status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return fallback
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  if (user.role !== role) return <Navigate to={homeFor(user.role)} replace />
  return children
}
