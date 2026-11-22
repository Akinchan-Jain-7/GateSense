import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { makeQueryClient } from '../src/app/App'
import { setTokens } from '../src/lib/api/tokens'
import { LiveProvider, socketUrl, useLive, useLiveStatus, type LiveMessage } from '../src/lib/live'
import { mockApi } from './utils'

/** The live connection: reconnects with backoff, catches up, refreshes a rejected token. */

class FakeSocket {
  static all: FakeSocket[] = []
  sent: string[] = []
  closed = false
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  url: string
  constructor(url: string) {
    this.url = url
    FakeSocket.all.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    this.closed = true
  }
  // What the server does:
  open() {
    act(() => this.onopen?.())
  }
  push(message: LiveMessage | string) {
    act(() =>
      this.onmessage?.({ data: typeof message === 'string' ? message : JSON.stringify(message) }),
    )
  }
  drop(code = 1006) {
    act(() => this.onclose?.({ code }))
  }
  static latest() {
    const socket = FakeSocket.all.at(-1)
    if (!socket) throw new Error('no socket yet')
    return socket
  }
}

function Probe({ onMessage }: { onMessage: (m: LiveMessage) => void }) {
  useLive(onMessage)
  return <p>status: {useLiveStatus()}</p>
}

function mount(onMessage: (m: LiveMessage) => void = () => undefined) {
  const client = makeQueryClient()
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const view = render(
    <QueryClientProvider client={client}>
      <LiveProvider enabled>
        <Probe onMessage={onMessage} />
      </LiveProvider>
    </QueryClientProvider>,
  )
  return { invalidate, ...view }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.all = []
  vi.stubGlobal('WebSocket', FakeSocket)
  setTokens({ access: 'access-1', refresh: 'refresh-1' })
})

afterEach(() => {
  vi.useRealTimers()
  setTokens(null)
})

describe('live connection', () => {
  it('connects with the access token and passes messages on', () => {
    const seen: LiveMessage[] = []
    const { invalidate } = mount((m) => seen.push(m))
    expect(FakeSocket.latest().url).toBe(socketUrl('access-1'))
    expect(screen.getByText('status: connecting')).toBeInTheDocument()

    FakeSocket.latest().open()
    expect(screen.getByText('status: live')).toBeInTheDocument()

    FakeSocket.latest().push({ type: 'alert.created', data: { plate: 'HR26DK8337' } })
    FakeSocket.latest().push({ type: 'pong' })
    FakeSocket.latest().push('not json')
    expect(seen).toEqual([{ type: 'alert.created', data: { plate: 'HR26DK8337' } }])
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['alerts'] })
  })

  it('pings to keep the connection open', () => {
    mount()
    FakeSocket.latest().open()
    act(() => {
      vi.advanceTimersByTime(25_000)
    })
    expect(FakeSocket.latest().sent).toEqual(['ping'])
  })

  it('reconnects with backoff and refetches everything once back', () => {
    vi.spyOn(Math, 'random').mockReturnValue(1) // the longest delay of each step
    const { invalidate } = mount()
    FakeSocket.latest().open()
    FakeSocket.latest().drop()
    expect(screen.getByText('status: reconnecting')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(999)
    })
    expect(FakeSocket.all).toHaveLength(1) // first retry after 1 s
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(FakeSocket.all).toHaveLength(2)

    FakeSocket.latest().drop() // the retry fails too: wait 2 s this time
    act(() => {
      vi.advanceTimersByTime(1999)
    })
    expect(FakeSocket.all).toHaveLength(2)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(FakeSocket.all).toHaveLength(3)

    invalidate.mockClear()
    FakeSocket.latest().open()
    expect(screen.getByText('status: live')).toBeInTheDocument()
    expect(invalidate).toHaveBeenCalledWith() // missed messages aren't replayed
  })

  it('reconnects straight away when the device comes back online', () => {
    mount()
    FakeSocket.latest().open()
    FakeSocket.latest().drop()
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    expect(FakeSocket.all).toHaveLength(2)
  })

  it('refreshes a rejected token once, then reconnects with the new one', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': { access_token: 'access-2', refresh_token: 'refresh-2' },
    })
    vi.spyOn(Math, 'random').mockReturnValue(0)
    mount()
    FakeSocket.latest().drop(4401)
    await act(async () => {
      await vi.runOnlyPendingTimersAsync()
    })
    expect(FakeSocket.latest().url).toBe(socketUrl('access-2'))
  })

  it('stops and closes the socket when the screen goes away', () => {
    const { unmount } = mount()
    const socket = FakeSocket.latest()
    socket.open()
    unmount()
    expect(socket.closed).toBe(true)
    socket.drop()
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(FakeSocket.all).toHaveLength(1)
  })
})
