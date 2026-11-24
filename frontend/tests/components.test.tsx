import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { Plate } from '../src/components/ui/plate'
import Login from '../src/features/auth/Login'
import Landing from '../src/features/landing/Landing'
import { ApprovalsPage } from '../src/features/resident/ApprovalsPage'
import { ResourcePage, type ResourceConfig } from '../src/features/admin/ResourcePage'
import { RequireRole } from '../src/lib/auth'
import { mockApi, page, renderRoutes, signInAs, user } from './utils'

const DEMO = {
  enabled: true,
  password: 'GateSense@123',
  accounts: [
    { role: 'guard', email: 'guard@example.com', name: 'Ramesh Yadav' },
    { role: 'resident', email: 'resident@example.com', name: 'Priya Sharma' },
    { role: 'admin', email: 'admin@example.com', name: 'Anil Mehta' },
  ],
}

describe('Plate', () => {
  it('reads the grouped plate to screen readers', () => {
    render(<Plate plate="UP16AB1234" />)
    expect(screen.getByRole('img', { name: 'Plate UP16 AB 1234' })).toBeInTheDocument()
  })
})

describe('Landing page', () => {
  it('offers one-click demo logins when the API is in demo mode', async () => {
    mockApi({ 'GET /api/v1/demo': DEMO })
    renderRoutes([{ path: '/', element: <Landing /> }], '/')
    expect(await screen.findByRole('button', { name: 'Try the guard console' })).toBeInTheDocument()
    expect(screen.getByText('GateSense@123')).toBeInTheDocument()
  })

  it('shows plain sign-in when demo mode is off', async () => {
    mockApi({ 'GET /api/v1/demo': { enabled: false, password: null, accounts: [] } })
    renderRoutes([{ path: '/', element: <Landing /> }], '/')
    expect(await screen.findAllByRole('link', { name: 'Sign in' })).not.toHaveLength(0)
    expect(screen.queryByRole('button', { name: 'Try the guard console' })).not.toBeInTheDocument()
  })

  it('demo button signs in and opens the role’s home', async () => {
    mockApi({
      'GET /api/v1/demo': DEMO,
      'POST /api/v1/auth/login': {
        access_token: 'a',
        refresh_token: 'r',
        expires_in: 900,
        token_type: 'bearer',
      },
      'GET /api/v1/me': user('guard'),
    })
    const { router } = renderRoutes(
      [
        { path: '/', element: <Landing /> },
        { path: '/guard', element: <p>console</p> },
      ],
      '/',
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Try the guard console' }))
    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/guard')
    })
  })

  it('switching demo roles opens the new role’s home', async () => {
    // Bug found in a live tour: signed in as the guard, "Try the resident app" landed on
    // /guard with the resident's token, because the signed-in user wasn't updated.
    signInAs('guard')
    mockApi({
      'GET /api/v1/demo': DEMO,
      'POST /api/v1/auth/login': {
        access_token: 'resident-token',
        refresh_token: 'resident-refresh',
        expires_in: 900,
        token_type: 'bearer',
      },
      'GET /api/v1/me': (request: Request) =>
        request.headers.get('Authorization') === 'Bearer resident-token'
          ? user('resident')
          : user('guard'),
    })
    const home = (role: 'guard' | 'resident') => (
      <RequireRole role={role} fallback={<p>loading</p>}>
        <p>{role} home</p>
      </RequireRole>
    )
    const { router } = renderRoutes(
      [
        { path: '/', element: <Landing /> },
        { path: '/guard', element: home('guard') },
        { path: '/resident', element: home('resident') },
      ],
      '/guard',
    )
    expect(await screen.findByText('guard home')).toBeInTheDocument() // the guard is known
    await router.navigate('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Try the resident app' }))
    expect(await screen.findByText('resident home')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/resident')
  })
})

describe('Login', () => {
  it('shows the API’s error message', async () => {
    mockApi({
      'GET /api/v1/demo': { enabled: false, password: null, accounts: [] },
      'POST /api/v1/auth/login': new Response(
        JSON.stringify({ detail: 'Invalid email or password' }),
        { status: 401 },
      ),
    })
    renderRoutes([{ path: '/login', element: <Login /> }], '/login')
    await userEvent.type(screen.getByLabelText('Email'), 'someone@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Invalid email or password')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('aria-invalid', 'true')
  })
})

describe('RequireRole', () => {
  it('sends signed-out people to the login page with a way back', async () => {
    mockApi({})
    const { router } = renderRoutes(
      [
        {
          path: '/admin',
          element: (
            <RequireRole role="admin" fallback={<p>loading</p>}>
              <p>admin</p>
            </RequireRole>
          ),
        },
        { path: '/login', element: <p>login page</p> },
      ],
      '/admin',
    )
    await screen.findByText('login page')
    expect(router.state.location.search).toBe('?next=%2Fadmin')
  })

  it('sends the wrong role to its own home', async () => {
    signInAs('guard')
    mockApi({ 'GET /api/v1/me': user('guard') })
    renderRoutes(
      [
        {
          path: '/admin',
          element: (
            <RequireRole role="admin" fallback={<p>loading</p>}>
              <p>admin</p>
            </RequireRole>
          ),
        },
        { path: '/guard', element: <p>guard home</p> },
      ],
      '/admin',
    )
    expect(await screen.findByText('guard home')).toBeInTheDocument()
  })
})

describe('Resident approvals', () => {
  const visit = {
    id: 'v1',
    flat_id: 'f1',
    flat_label: 'B-402',
    visitor_name: 'Varun Chopra',
    visitor_phone: '+91 92•••••520',
    plate_normalized: '22BH4502EW',
    category: 'cab',
    purpose: 'Uber pickup',
    status: 'pending_approval',
    created_at: new Date().toISOString(),
    entered_at: null,
    exited_at: null,
    expected_exit_at: null,
    duration_minutes: null,
    approved_by_id: null,
    registered_by_id: null,
    entry_event_id: null,
    guest_pass_id: null,
  }
  const approval = {
    id: 'a1',
    status: 'pending',
    channel: null,
    decided_at: null,
    decided_by_id: null,
    requested_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 170_000).toISOString(),
    visit,
  }

  it('removes the card as soon as the resident approves', async () => {
    signInAs('resident')
    let pending = [approval]
    const api = mockApi({
      'GET /api/v1/me': user('resident', [{ id: 'f1', label: 'B-402' }]),
      'GET /api/v1/approvals': () => page(pending),
      'GET /api/v1/visits': page([]),
      'POST /api/v1/approvals/a1/decision': () => {
        pending = []
        return { ...approval, status: 'approved' }
      },
    })
    renderRoutes([{ path: '/resident', element: <ApprovalsPage /> }], '/resident')
    expect(await screen.findByText('Varun Chopra')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Plate 22 BH 4502 EW' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    })
    const decision = api.calls.find((r) => r.url.endsWith('/approvals/a1/decision'))
    expect(await decision?.clone().json()).toEqual({ decision: 'approve' })
    expect(await screen.findByText('Varun Chopra can come in')).toBeInTheDocument()
  })
})

describe('ResourcePage', () => {
  type Row = { id: string; name: string }
  function config(rows: Row[], seen: string[]): ResourceConfig<Row> {
    return {
      key: 'things',
      title: 'Things',
      singular: 'Thing',
      description: 'Test things.',
      search: 'Search things',
      list: ({ q }) => {
        seen.push(q ?? '')
        const items = rows.filter((r) => !q || r.name.includes(q))
        return Promise.resolve({ items, total: items.length, limit: 20, offset: 0 })
      },
      columns: [{ header: 'Name', cell: (r) => r.name }],
    }
  }

  it('lists rows, searches after a pause, and shows an empty state', async () => {
    mockApi({})
    const seen: string[] = []
    renderRoutes(
      [
        {
          path: '/',
          element: (
            <ResourcePage
              config={config(
                [
                  { id: '1', name: 'Alpha' },
                  { id: '2', name: 'Beta' },
                ],
                seen,
              )}
            />
          ),
        },
      ],
      '/',
    )
    expect(await screen.findByText('Alpha')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Search things'), 'zzz')
    expect(await screen.findByText('Nothing matches')).toBeInTheDocument()
    expect(seen.at(-1)).toBe('zzz')
  })
})
