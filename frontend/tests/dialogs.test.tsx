import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { CodeDialog } from '../src/features/guard/CodeDialog'
import { ProfilePage } from '../src/features/resident/ProfilePage'
import { setTokens } from '../src/lib/api/tokens'
import { mockApi, renderRoutes, signInAs, user } from './utils'

/** Smaller flows: a guest code at the gate, and linking Telegram from the profile. */

function GateWithCode() {
  const [open, setOpen] = useState(true)
  return open ? <CodeDialog open onOpenChange={setOpen} /> : <p>dialog closed</p>
}

describe('Guest pass code at the gate', () => {
  it('cleans up the typed code, admits the guest and closes', async () => {
    signInAs('guard')
    const api = mockApi({
      'GET /api/v1/me': user('guard'),
      'POST /api/v1/guest-passes/redeem': { id: 'v1', visitor_name: 'Meera Iyer' },
    })
    renderRoutes([{ path: '/', element: <GateWithCode /> }], '/')
    const input = await screen.findByLabelText('Code')
    const submit = screen.getByRole('button', { name: 'Check code' })
    await userEvent.type(input, 'k7m')
    expect(submit).toBeDisabled() // too short
    await userEvent.type(input, ' 4qx2')
    await userEvent.click(submit)
    expect(await screen.findByText('Meera Iyer is expected. Let them in.')).toBeInTheDocument()
    expect(screen.getByText('dialog closed')).toBeInTheDocument()
    const request = api.calls.find((r) => r.url.endsWith('/redeem'))
    expect(await request?.clone().json()).toEqual({ code: 'K7M4QX2' })
  })

  it('says why a code was refused', async () => {
    signInAs('guard')
    mockApi({
      'GET /api/v1/me': user('guard'),
      'POST /api/v1/guest-passes/redeem': new Response(
        JSON.stringify({ detail: 'This pass has already been used' }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    })
    renderRoutes([{ path: '/', element: <GateWithCode /> }], '/')
    await userEvent.type(await screen.findByLabelText('Code'), 'K7M4QX2')
    await userEvent.click(screen.getByRole('button', { name: 'Check code' }))
    expect(await screen.findByText(/already been used/)).toBeInTheDocument()
    expect(screen.queryByText('dialog closed')).not.toBeInTheDocument()
  })
})

describe('Resident profile', () => {
  it('gets a Telegram link code, and can disconnect', async () => {
    setTokens({ access: 'resident-token', refresh: 'resident-refresh' })
    const api = mockApi({
      'GET /api/v1/me': {
        ...user('resident', [{ id: 'f1', label: 'B-402' }]),
        phone: '+919812345678',
      },
      'POST /api/v1/telegram/link-code': {
        code: 'LNK42Q',
        link: 'https://t.me/GateSenseBot?start=LNK42Q',
        expires_in_seconds: 600,
      },
      'DELETE /api/v1/telegram/link': new Response(null, { status: 204 }),
    })
    renderRoutes([{ path: '/', element: <ProfilePage /> }], '/')
    expect(await screen.findByText('Priya Sharma')).toBeInTheDocument()
    expect(screen.getByText('Flat B-402')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Disconnect' }))
    expect(await screen.findByText(/Telegram disconnected/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Connect Telegram' }))
    expect(await screen.findByRole('link', { name: 'Open Telegram to connect' })).toHaveAttribute(
      'href',
      'https://t.me/GateSenseBot?start=LNK42Q',
    )
    expect(screen.getByText('/start LNK42Q')).toBeInTheDocument()
    expect(screen.getByText(/works for 10 minutes/)).toBeInTheDocument()
    await waitFor(() => {
      expect(api.calls.filter((r) => r.method !== 'GET')).toHaveLength(2)
    })
  })
})
