import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { Toaster } from 'sonner'
import { vi } from 'vitest'

import { makeQueryClient, Providers } from '../src/app/App'
import { LiveProvider } from '../src/lib/live'

type Handler = (request: Request) => unknown

/**
 * A fake API: map "METHOD /path" to a JSON body (or a function of the request).
 * Return `new Response(...)` from a handler to send an error.
 */
export function mockApi(routes: Record<string, unknown>) {
  const calls: Request[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const request =
      input instanceof Request
        ? input
        : new Request(new URL(String(input), 'http://localhost'), init)
    calls.push(request)
    const url = new URL(request.url)
    const key = `${request.method} ${url.pathname}`
    const handler = routes[key]
    if (handler === undefined)
      return Promise.resolve(
        new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 404 }),
      )
    const value: unknown = typeof handler === 'function' ? (handler as Handler)(request) : handler
    if (value instanceof Response) return Promise.resolve(value)
    return Promise.resolve(
      new Response(JSON.stringify(value), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function signInAs(role: 'guard' | 'resident' | 'admin') {
  localStorage.setItem(
    'gatesense.tokens',
    JSON.stringify({ access: `${role}-token`, refresh: `${role}-refresh` }),
  )
}

export function user(
  role: 'guard' | 'resident' | 'admin',
  flats: { id: string; label: string }[] = [],
) {
  return {
    id: `${role}-id`,
    society_id: 's1',
    email: `${role}@example.com`,
    full_name: { guard: 'Ramesh Yadav', resident: 'Priya Sharma', admin: 'Anil Mehta' }[role],
    phone: null,
    role,
    last_login_at: null,
    flats,
  }
}

export function renderRoutes(routes: { path: string; element: ReactNode }[], initial: string) {
  const router = createMemoryRouter(routes, { initialEntries: [initial] })
  const client = makeQueryClient()
  client.setDefaultOptions({ queries: { retry: false } })
  render(
    <Providers client={client}>
      <LiveProvider enabled={false}>
        <RouterProvider router={router} />
        <Toaster />
      </LiveProvider>
    </Providers>,
  )
  return { router, client }
}

export function page<T>(items: T[]) {
  return { items, total: items.length, limit: 20, offset: 0 }
}
