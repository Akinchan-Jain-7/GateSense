import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import AdminApp from '../src/features/admin/AdminApp'
import { mockApi, page, renderRoutes, signInAs, user } from './utils'

/** The admin's management pages: list, search, filter, page, add, edit, delete. */

const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString()

async function bodyOf(calls: Request[], method: string, suffix: string): Promise<unknown> {
  const request = calls.find((r) => r.method === method && new URL(r.url).pathname.endsWith(suffix))
  if (!request) throw new Error(`no ${method} ${suffix}`)
  return request.clone().json()
}

function query(calls: Request[], path: string): URLSearchParams[] {
  return calls
    .filter((r) => r.method === 'GET' && new URL(r.url).pathname === path)
    .map((r) => new URL(r.url).searchParams)
}

function flat(id: string, label: string, floor: number | null = 4) {
  const [block, number] = label.split('-')
  return { id, label, block, number, floor, parking_slots: 1, society_id: 's1' }
}

function openAdmin(path: string, routes: Record<string, unknown>) {
  signInAs('admin')
  const api = mockApi({ 'GET /api/v1/me': user('admin'), ...routes })
  renderRoutes([{ path: '/admin/*', element: <AdminApp /> }], path)
  return api
}

describe('Flats', () => {
  it('adds, edits and deletes a flat', async () => {
    const api = openAdmin('/admin/flats', {
      'GET /api/v1/flats': page([flat('f1', 'B-402'), flat('f2', 'A-101', null)]),
      'POST /api/v1/flats': flat('f3', 'C-203'),
      'PATCH /api/v1/flats/f1': flat('f1', 'B-402', 5),
      'DELETE /api/v1/flats/f2': new Response(null, { status: 204 }),
    })
    const table = await screen.findByRole('table')
    expect(within(table).getByText('B-402')).toBeInTheDocument()
    expect(within(table).getByText('—')).toBeInTheDocument() // A-101 has no floor

    await userEvent.click(screen.getByRole('button', { name: 'Add flat' }))
    const add = await screen.findByRole('dialog', { name: 'Add flat' })
    await userEvent.type(within(add).getByLabelText(/Block/), 'C')
    await userEvent.type(within(add).getByLabelText(/Flat number/), '203')
    await userEvent.type(within(add).getByLabelText('Floor'), '2')
    await userEvent.click(within(add).getByRole('button', { name: 'Add flat' }))
    expect(await bodyOf(api.calls, 'POST', '/flats')).toMatchObject({
      block: 'C',
      number: '203',
      floor: 2,
    })

    const rowB = screen.getByRole('row', { name: /B-402/ })
    await userEvent.click(within(rowB).getByRole('button', { name: 'Edit flat' }))
    const edit = await screen.findByRole('dialog', { name: 'Edit flat' })
    const floor = within(edit).getByLabelText('Floor')
    expect(floor).toHaveValue(4)
    await userEvent.clear(floor)
    await userEvent.type(floor, '5')
    await userEvent.click(within(edit).getByRole('button', { name: 'Save changes' }))
    expect(await bodyOf(api.calls, 'PATCH', '/flats/f1')).toMatchObject({ floor: 5 })

    const rowA = screen.getByRole('row', { name: /A-101/ })
    await userEvent.click(within(rowA).getByRole('button', { name: 'Delete flat' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(within(confirm).getByText(/A-101 will be removed/)).toBeInTheDocument()
    await userEvent.click(within(confirm).getByRole('button', { name: 'Delete flat' }))
    await waitFor(() => {
      expect(api.calls.some((r) => r.method === 'DELETE')).toBe(true)
    })
    expect(await screen.findByText('Flat deleted')).toBeInTheDocument()
  })

  it('shows what the server rejected and keeps the form open', async () => {
    openAdmin('/admin/flats', {
      'GET /api/v1/flats': page([]),
      'POST /api/v1/flats': new Response(JSON.stringify({ detail: 'Flat B-402 already exists' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
    })
    expect(await screen.findByText('No flats yet')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add the first one' }))
    const add = await screen.findByRole('dialog', { name: 'Add flat' })
    await userEvent.type(within(add).getByLabelText(/Block/), 'B')
    await userEvent.type(within(add).getByLabelText(/Flat number/), '402')
    await userEvent.click(within(add).getByRole('button', { name: 'Add flat' }))
    expect(await screen.findByText(/Flat B-402 already exists/)).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Add flat' })).toBeInTheDocument()
  })

  it('searches after a pause, pages through results and clears an empty search', async () => {
    const api = openAdmin('/admin/flats', {
      'GET /api/v1/flats': (request: Request) => {
        const params = new URL(request.url).searchParams
        if (params.get('q') === 'Z-999') return page([])
        const offset = Number(params.get('offset') ?? 0)
        return {
          items: [flat(`f${String(offset)}`, offset ? 'C-301' : 'B-402')],
          total: 45,
          limit: 20,
          offset,
        }
      },
    })
    expect(await screen.findByText('1–20 of 45')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(await screen.findByText('C-301')).toBeInTheDocument()
    expect(query(api.calls, '/api/v1/flats').at(-1)?.get('offset')).toBe('20')

    await userEvent.type(screen.getByLabelText('Search flats, e.g. B-402'), 'Z-999')
    expect(await screen.findByText('Nothing matches')).toBeInTheDocument()
    expect(query(api.calls, '/api/v1/flats').at(-1)?.get('q')).toBe('Z-999')
    await userEvent.click(screen.getByRole('button', { name: 'Clear search' }))
    expect(await screen.findByText('B-402')).toBeInTheDocument()
  })

  it('offers a retry when the list fails to load', async () => {
    let failures = 1
    openAdmin('/admin/flats', {
      'GET /api/v1/flats': () =>
        failures-- > 0
          ? new Response(JSON.stringify({ detail: 'Database is restarting' }), { status: 503 })
          : page([flat('f1', 'B-402')]),
    })
    expect(await screen.findByText(/Database is restarting/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(await screen.findByText('B-402')).toBeInTheDocument()
  })
})

describe('Gates and cameras', () => {
  it('rotates a camera key and shows the new key once', async () => {
    const gate = { id: 'g1', name: 'Main Gate', location: 'Sector 150 road', is_active: true }
    const camera = {
      id: 'd1',
      name: 'Main Gate - entry camera',
      gate_id: 'g1',
      gate_name: 'Main Gate',
      direction: 'entry',
      api_key_prefix: 'gsd_AbC1',
      is_active: true,
      last_seen_at: iso(-60_000),
    }
    const api = openAdmin('/admin/gates', {
      'GET /api/v1/gates': page([gate]),
      'GET /api/v1/devices': page([camera]),
      'POST /api/v1/devices/d1/rotate-key': { ...camera, api_key: 'gsd_new-secret-key' },
    })
    expect(await screen.findByText('Main Gate - entry camera')).toBeInTheDocument()
    expect(screen.getByText('gsd_AbC1…')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Rotate camera key' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(within(confirm).getByText(/stops working until its new key/)).toBeInTheDocument()
    await userEvent.click(within(confirm).getByRole('button', { name: 'Rotate key' }))
    const shown = await screen.findByRole('dialog', { name: 'Camera key' })
    expect(within(shown).getByText('gsd_new-secret-key')).toBeInTheDocument()
    expect(api.calls.some((r) => r.url.endsWith('/rotate-key'))).toBe(true)
  })
})

describe('Records', () => {
  it('lists visits with masked phones and filters by status', async () => {
    const api = openAdmin('/admin/visits', {
      'GET /api/v1/visits': page([
        {
          id: 'v1',
          visitor_name: 'Rahul Kumar',
          visitor_phone: '+91 98•••••210',
          flat_label: 'B-402',
          category: 'delivery',
          purpose: 'Swiggy order',
          plate_normalized: 'DL3CAB1234',
          status: 'exited',
          entered_at: iso(-3_600_000),
          exited_at: iso(-3_000_000),
        },
        {
          id: 'v2',
          visitor_name: null,
          visitor_phone: null,
          flat_label: 'A-101',
          category: 'guest',
          purpose: null,
          plate_normalized: null,
          status: 'inside',
          entered_at: iso(-600_000),
          exited_at: null,
        },
      ]),
    })
    expect(await screen.findByText('Rahul Kumar')).toBeInTheDocument()
    expect(screen.getByText('+91 98•••••210')).toBeInTheDocument()
    expect(screen.getByText('10 min')).toBeInTheDocument()
    expect(screen.getByText('Guest pass')).toBeInTheDocument()
    expect(screen.getByText('On foot')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'overstayed')
    await waitFor(() => {
      expect(query(api.calls, '/api/v1/visits').at(-1)?.get('status')).toBe('overstayed')
    })
  })

  it('shows audit entries with what changed', async () => {
    openAdmin('/admin/audit', {
      'GET /api/v1/audit-logs': page([
        {
          id: 'a1',
          created_at: iso(-60_000),
          actor: { id: 'u1', full_name: 'Anil Mehta' },
          action: 'settings.update',
          entity_type: 'settings',
          entity_id: 's1',
          changes: { cab_minutes: { from: 10, to: 15 } },
        },
        {
          id: 'a2',
          created_at: iso(-120_000),
          actor: null,
          action: 'flat.create',
          entity_type: 'flat',
          entity_id: 'f9',
          changes: { label: [null, 'C-203'] },
        },
      ]),
    })
    expect(await screen.findByText('Anil Mehta')).toBeInTheDocument()
    expect(screen.getByText(': 10 → 15', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('Removed user')).toBeInTheDocument()
    expect(screen.getByText(/null → C-203/)).toBeInTheDocument()
  })

  it('marks a gate check as checked', async () => {
    let resolved = false
    const flag = (done: boolean) => ({
      id: 'r1',
      kind: 'exit_without_entry',
      details: 'UP16AB1234 left at 03:12 with no entry on record',
      created_at: iso(-3_600_000),
      resolved_at: done ? iso(0) : null,
    })
    const api = openAdmin('/admin/checks', {
      'GET /api/v1/reconciliation': () => page([flag(resolved)]),
      'POST /api/v1/reconciliation/r1/resolve': () => {
        resolved = true
        return flag(true)
      },
    })
    expect(await screen.findByText('Exit without an entry')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Mark checked' }))
    expect(await screen.findByText('Checked', { selector: 'span' })).toBeInTheDocument()
    expect(api.calls.some((r) => r.url.endsWith('/resolve'))).toBe(true)
  })
})
