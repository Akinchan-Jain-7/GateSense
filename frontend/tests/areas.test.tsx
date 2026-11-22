/**
 * Whole areas rendered against a fake API: the guard console, the resident app and the
 * admin dashboard. The Playwright journeys cover the real stack; these cover the screens'
 * behaviour quickly and in detail.
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import AdminApp from '../src/features/admin/AdminApp'
import GuardConsole from '../src/features/guard/GuardConsole'
import ResidentApp from '../src/features/resident/ResidentApp'
import { setLanguage } from '../src/i18n'
import { mockApi, page, renderRoutes, signInAs, user } from './utils'

const now = Date.now()
const iso = (msFromNow: number) => new Date(now + msFromNow).toISOString()

function visit(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    flat_id: 'f1',
    flat_label: 'B-402',
    visitor_name: `Visitor ${id}`,
    visitor_phone: '+91 98•••••210',
    plate_normalized: null,
    category: 'guest',
    purpose: 'Family visit',
    status: 'pending_approval',
    created_at: iso(-60_000),
    entered_at: null,
    exited_at: null,
    expected_exit_at: null,
    duration_minutes: null,
    ...overrides,
  }
}

function gateEvent(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    gate_id: 'g1',
    device_id: 'd1',
    direction: 'entry',
    plate_raw: 'UP16AB1234',
    plate_normalized: 'UP16AB1234',
    ocr_fixes: 0,
    confidence: 0.96,
    captured_at: iso(-120_000),
    received_at: iso(-119_000),
    match_result: 'resident',
    match_distance: 0,
    vehicle_id: 'veh1',
    visit_id: null,
    paired_event_id: null,
    needs_review: false,
    review_reason: null,
    reviewed_at: null,
    has_snapshot: false,
    ...overrides,
  }
}

function wideScreen() {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('min-width: 1024px'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }))
}

async function bodyOf(calls: Request[], suffix: string): Promise<unknown> {
  const request = calls.find((r) => r.method !== 'GET' && new URL(r.url).pathname.endsWith(suffix))
  if (!request) throw new Error(`no call to ${suffix}`)
  return request.clone().json()
}

describe('Guard console', () => {
  function guardApi() {
    return mockApi({
      'GET /api/v1/me': user('guard'),
      'GET /api/v1/gate-events': page([
        gateEvent('e1'),
        gateEvent('e2', {
          plate_raw: 'DL3CAF229O',
          plate_normalized: 'DL3CAF2290',
          match_result: 'low_confidence',
          confidence: 0.61,
          needs_review: true,
          review_reason: 'low_confidence',
        }),
        gateEvent('e3', {
          plate_raw: 'KA05MN0042',
          plate_normalized: 'KA05MN0042',
          match_result: 'unknown',
          vehicle_id: null,
        }),
      ]),
      'GET /api/v1/visits': (request: Request) => {
        const url = new URL(request.url)
        if (url.searchParams.get('status') === 'approved')
          return page([visit('arriving', { status: 'approved' })])
        if (url.searchParams.get('inside') === 'true') {
          return page([
            visit('inside', {
              status: 'inside',
              entered_at: iso(-3_600_000),
              expected_exit_at: iso(-600_000),
            }),
          ])
        }
        return page([])
      },
      'GET /api/v1/approvals': page([
        {
          id: 'a1',
          status: 'pending',
          requested_at: iso(-30_000),
          expires_at: iso(150_000),
          visit: visit('asking'),
        },
        {
          id: 'a2',
          status: 'timed_out',
          requested_at: iso(-400_000),
          expires_at: iso(-220_000),
          visit: visit('nobody'),
        },
      ]),
      'GET /api/v1/alerts': page([
        {
          id: 'al1',
          kind: 'watchlist',
          severity: 'high',
          message: 'Watchlisted vehicle HR26DK8337 is entering',
          gate_event_id: null,
          created_at: iso(-60_000),
        },
      ]),
      'GET /api/v1/escalations': page([
        {
          id: 't1',
          status: 'open',
          created_at: iso(-60_000),
          visit: visit('late', { status: 'escalated', expected_exit_at: iso(-4_500_000) }),
          contacts: [{ name: 'Priya Sharma', phone: '+919812345678', is_primary_contact: true }],
        },
      ]),
      'GET /api/v1/analytics/inside': {
        vehicles_inside: 57,
        visitors_inside: 3,
        residents_inside: 54,
        visitor_vehicles_inside: 2,
        visitor_parking_slots: 20,
      },
      'GET /api/v1/flats': page([
        { id: 'f1', label: 'B-402', block: 'B', number: '402', floor: 4, parking_slots: 1 },
      ]),
      'POST /api/v1/visits/nobody/decision': visit('nobody', { status: 'approved' }),
      'POST /api/v1/alerts/al1/acknowledge': { id: 'al1' },
      'POST /api/v1/escalations/t1/resolve': { id: 't1', status: 'resolved' },
      'POST /api/v1/gate-events/e2/review': gateEvent('e2', { reviewed_at: iso(0) }),
      'POST /api/v1/visits': { visit: visit('new', { visitor_name: 'Kabir Rao' }), approval: null },
    })
  }

  it('shows every column and lets the guard decide, acknowledge and log a call', async () => {
    wideScreen()
    signInAs('guard')
    const api = guardApi()
    renderRoutes([{ path: '/guard', element: <GuardConsole /> }], '/guard')

    expect(await screen.findByRole('heading', { name: 'Gate console' })).toBeInTheDocument()
    expect(await screen.findByText('57')).toBeInTheDocument()
    expect(await screen.findByText('Visitor asking')).toBeInTheDocument()
    expect(screen.getByText('Approved, on the way in')).toBeInTheDocument()
    expect(screen.getByText('Visitor inside')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Priya Sharma/ })).toHaveAttribute(
      'href',
      'tel:+919812345678',
    )

    const waiting = screen.getByRole('region', { name: 'Waiting for a decision' })
    await userEvent.click(within(waiting).getByRole('button', { name: 'Let in' }))
    expect(await bodyOf(api.calls, '/visits/nobody/decision')).toEqual({ decision: 'approve' })

    await userEvent.click(screen.getByRole('button', { name: 'Mark seen' }))
    await userEvent.click(screen.getByRole('button', { name: 'Spoke to them' }))
    expect(await bodyOf(api.calls, '/escalations/t1/resolve')).toEqual({ outcome: 'reached' })
    expect(await screen.findByText('Marked as spoken to')).toBeInTheDocument()
  })

  it('reviews an uncertain plate and offers to register an unknown car', async () => {
    wideScreen()
    signInAs('guard')
    const api = guardApi()
    renderRoutes([{ path: '/guard', element: <GuardConsole /> }], '/guard')

    expect(await screen.findByText('Plate needs a check')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Fix plate' }))
    const input = screen.getByLabelText('Correct plate number')
    await userEvent.clear(input)
    await userEvent.type(input, 'dl 3c af 2290')
    await userEvent.click(screen.getByRole('button', { name: 'Save plate' }))
    expect(await bodyOf(api.calls, '/gate-events/e2/review')).toEqual({
      action: 'correct',
      plate: 'DL3CAF2290',
    })

    const arrivals = screen.getByRole('region', { name: 'Arrivals' })
    await userEvent.click(within(arrivals).getByRole('button', { name: 'Register visitor' }))
    const dialog = await screen.findByRole('dialog', { name: 'Register a visitor' })
    expect(within(dialog).getByLabelText('Vehicle number (optional)')).toHaveValue('KA05MN0042')
    await userEvent.type(within(dialog).getByLabelText('Visitor name'), 'Kabir Rao')
    await userEvent.type(within(dialog).getByLabelText('Mobile number'), '9876543210')
    await userEvent.selectOptions(within(dialog).getByLabelText('Flat'), 'B-402')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Ask the resident' }))
    const body = (await bodyOf(api.calls, '/api/v1/visits')) as Record<string, unknown>
    expect(body).toMatchObject({
      full_name: 'Kabir Rao',
      flat_id: 'f1',
      plate: 'KA05MN0042',
      gate_event_id: 'e3',
      category: 'guest',
    })
    expect(await screen.findByText('Asked B-402 to approve Kabir Rao')).toBeInTheDocument()
  })

  it('switches to Hindi', async () => {
    wideScreen()
    signInAs('guard')
    guardApi()
    renderRoutes([{ path: '/guard', element: <GuardConsole /> }], '/guard')
    await userEvent.click(await screen.findByRole('button', { name: 'Switch to Hindi' }))
    expect(await screen.findByRole('heading', { name: 'गेट कंसोल' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'निर्णय की प्रतीक्षा' })).toBeInTheDocument()
    setLanguage('en')
  })

  it('uses tabs on a phone', async () => {
    signInAs('guard')
    guardApi()
    renderRoutes([{ path: '/guard', element: <GuardConsole /> }], '/guard')
    await userEvent.click(await screen.findByRole('tab', { name: 'Alerts' }))
    expect(await screen.findByText('Watchlist vehicle at the gate')).toBeInTheDocument()
  })
})

describe('Resident app', () => {
  it('creates a code guest pass and shows the code once', async () => {
    signInAs('resident')
    const api = mockApi({
      'GET /api/v1/me': user('resident', [{ id: 'f1', label: 'B-402' }]),
      'GET /api/v1/approvals': page([]),
      'GET /api/v1/guest-passes': page([]),
      'POST /api/v1/guest-passes': {
        code: 'K7QM2XRT',
        guest_pass: {
          id: 'gp1',
          guest_name: 'Meera Iyer',
          plate_normalized: null,
          has_code: true,
          valid_from: iso(0),
          valid_until: iso(4 * 3_600_000),
          max_uses: 1,
          use_count: 0,
          category: 'guest',
        },
      },
    })
    renderRoutes([{ path: '/resident/*', element: <ResidentApp /> }], '/resident/passes')

    await userEvent.click(await screen.findByRole('button', { name: 'New pass' }))
    await userEvent.type(screen.getByLabelText('Guest’s name'), 'Meera Iyer')
    await userEvent.click(screen.getByText('A code they show'))
    await userEvent.click(screen.getByRole('button', { name: 'Create guest pass' }))

    expect(await screen.findByText('K7QM2XRT')).toBeInTheDocument()
    const body = (await bodyOf(api.calls, '/api/v1/guest-passes')) as Record<string, unknown>
    expect(body).toMatchObject({
      guest_name: 'Meera Iyer',
      with_code: true,
      plate: null,
      max_uses: 1,
    })
  })

  it('shows the visit history and the profile', async () => {
    signInAs('resident')
    mockApi({
      'GET /api/v1/me': user('resident', [{ id: 'f1', label: 'B-402' }]),
      'GET /api/v1/approvals': page([]),
      'GET /api/v1/visits': page([
        visit('h1', { status: 'exited', entered_at: iso(-7_200_000), exited_at: iso(-3_600_000) }),
      ]),
    })
    renderRoutes([{ path: '/resident/*', element: <ResidentApp /> }], '/resident/history')
    expect(await screen.findByText('Visitor h1')).toBeInTheDocument()
    expect(screen.getByText(/stayed 1 h/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Profile' }))
    expect(await screen.findByRole('button', { name: /Connect Telegram/ })).toBeInTheDocument()
  })
})

describe('Admin dashboard', () => {
  const overview = {
    days: 14,
    since: iso(-14 * 86_400_000),
    visits: 339,
    average_visit_minutes: 47,
    overstayed_visits: 27,
    overstay_rate: 0.0796,
    vehicles_inside: 77,
    visitors_inside: 3,
    residents_inside: 74,
    visitor_vehicles_inside: 3,
    visitor_parking_slots: 20,
    busiest_hours: Array.from({ length: 24 }, (_, hour) => ({
      hour,
      residents: hour,
      visitors: 1,
    })),
    daily_visits: [{ day: '2026-11-20', visits: 24 }],
    categories: [{ category: 'delivery', visits: 172, average_minutes: 13 }],
    frequent_visitors: [
      {
        visitor_id: 'v1',
        name: 'Vikas Pal',
        phone_masked: '+91 96•••••944',
        visits: 27,
        last_visit_at: iso(-3_600_000),
        flats: ['A-101', 'B-402'],
      },
    ],
  }

  it('shows the overview with numbers, charts as tables and frequent visitors', async () => {
    signInAs('admin')
    mockApi({ 'GET /api/v1/me': user('admin'), 'GET /api/v1/analytics/overview': overview })
    renderRoutes([{ path: '/admin/*', element: <AdminApp /> }], '/admin')
    expect(await screen.findByText('339')).toBeInTheDocument()
    expect(screen.getByText('8.0%')).toBeInTheDocument()
    expect(screen.getByText('3 of 20')).toBeInTheDocument()
    expect(screen.getByText('Vikas Pal')).toBeInTheDocument()
    expect(screen.getAllByText('View as table')).toHaveLength(3)
  })

  it('lists vehicles and saves settings', async () => {
    signInAs('admin')
    const api = mockApi({
      'GET /api/v1/me': user('admin'),
      'GET /api/v1/vehicles': page([
        {
          id: 'veh1',
          plate_normalized: 'UP16AB1234',
          flat: { id: 'f1', label: 'B-402' },
          vehicle_type: 'car',
          make_model: 'Maruti Swift',
          colour: 'Red',
          is_active: true,
        },
      ]),
      'GET /api/v1/settings/visits': {
        guest_minutes: 240,
        delivery_minutes: 20,
        cab_minutes: 10,
        service_minutes: 120,
        approval_timeout_seconds: 180,
        visitor_retention_days: 90,
        plate_confidence_threshold: 0.8,
        visitor_parking_slots: 20,
      },
      'GET /api/v1/demo': { enabled: false, password: null, accounts: [] },
      'PATCH /api/v1/settings/visits': {},
    })
    renderRoutes([{ path: '/admin/*', element: <AdminApp /> }], '/admin/vehicles')
    expect(await screen.findByRole('img', { name: 'Plate UP16 AB 1234' })).toBeInTheDocument()
    expect(screen.getByText('Car, Maruti Swift, Red')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('link', { name: 'Settings' }))
    const cabs = await screen.findByLabelText('Cabs')
    await userEvent.clear(cabs)
    await userEvent.type(cabs, '15')
    expect(screen.getByText('1 unsaved change')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await bodyOf(api.calls, '/settings/visits')).toEqual({ cab_minutes: 15 })
  })
})
