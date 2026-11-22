/**
 * One WebSocket per signed-in tab, shared by every screen.
 *
 * - The server pushes `{type, at, data}` messages (see backend app/services/realtime.py).
 * - Each message invalidates the matching cached queries, so lists refetch on their own;
 *   screens can also subscribe to react immediately (e.g. a toast for a new alert).
 * - If the connection drops, we reconnect with exponential backoff and, once back,
 *   refetch everything: messages sent while we were away are not replayed.
 * - Close code 4401 means the token was rejected: refresh it once, then reconnect.
 */
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

import { API_BASE, refreshOnce } from './api/client'
import { getTokens, setTokens } from './api/tokens'
import { reconnectDelay } from './backoff'

export type LiveStatus = 'connecting' | 'live' | 'reconnecting'

export interface LiveMessage {
  type: string
  at?: string
  data?: unknown
}

type Handler = (message: LiveMessage) => void

interface LiveState {
  status: LiveStatus
  subscribe: (handler: Handler) => () => void
}

const LiveContext = createContext<LiveState | null>(null)
const PING_EVERY_MS = 25_000
const UNAUTHORIZED = 4401

/** Which cached lists a message makes stale. */
export const INVALIDATES: Record<string, string[][]> = {
  'gate_event.created': [['gate-events'], ['review-queue']],
  'alert.created': [['alerts']],
  'visit.updated': [['visits']],
  'approval.requested': [['approvals'], ['visits']],
  'approval.decided': [['approvals'], ['visits']],
  'approval.timed_out': [['approvals'], ['visits']],
  'escalation.created': [['escalations'], ['visits']],
  'escalation.resolved': [['escalations'], ['visits']],
}

export function applyMessage(client: QueryClient, message: LiveMessage): void {
  for (const queryKey of INVALIDATES[message.type] ?? []) {
    void client.invalidateQueries({ queryKey })
  }
}

export function socketUrl(token: string): string {
  const origin = API_BASE || `${window.location.protocol}//${window.location.host}`
  return `${origin.replace(/^http/, 'ws')}/api/v1/ws?token=${encodeURIComponent(token)}`
}

export function LiveProvider({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<LiveStatus>('connecting')
  const handlers = useRef(new Set<Handler>())

  useEffect(() => {
    if (!enabled) return
    let socket: WebSocket | null = null
    let attempt = 0
    let retryTimer: ReturnType<typeof setTimeout> | undefined
    let pingTimer: ReturnType<typeof setInterval> | undefined
    let stopped = false
    let hadConnection = false

    const scheduleReconnect = () => {
      if (stopped) return
      setStatus('reconnecting')
      clearTimeout(retryTimer)
      retryTimer = setTimeout(connect, reconnectDelay(attempt))
      attempt += 1
    }

    function connect() {
      const tokens = getTokens()
      if (stopped || !tokens) return
      socket = new WebSocket(socketUrl(tokens.access))
      socket.onopen = () => {
        attempt = 0
        setStatus('live')
        if (hadConnection) void queryClient.invalidateQueries() // catch up on what we missed
        hadConnection = true
        pingTimer = setInterval(() => {
          socket?.send('ping')
        }, PING_EVERY_MS)
      }
      socket.onmessage = (event: MessageEvent<string>) => {
        let message: LiveMessage
        try {
          message = JSON.parse(event.data) as LiveMessage
        } catch {
          return
        }
        if (message.type === 'pong') return
        applyMessage(queryClient, message)
        for (const handler of handlers.current) handler(message)
      }
      socket.onclose = (event) => {
        clearInterval(pingTimer)
        socket = null
        if (stopped) return
        if (event.code === UNAUTHORIZED) {
          void refreshOnce().then((ok) => {
            if (ok) scheduleReconnect()
            else setTokens(null)
          })
          return
        }
        scheduleReconnect()
      }
    }

    const reconnectNow = () => {
      if (socket) return
      attempt = 0
      clearTimeout(retryTimer)
      connect()
    }

    connect()
    window.addEventListener('online', reconnectNow)
    return () => {
      stopped = true
      clearTimeout(retryTimer)
      clearInterval(pingTimer)
      window.removeEventListener('online', reconnectNow)
      socket?.close()
    }
  }, [enabled, queryClient])

  const [value] = useState<Omit<LiveState, 'status'>>(() => ({
    subscribe: (handler: Handler) => {
      handlers.current.add(handler)
      return () => {
        handlers.current.delete(handler)
      }
    },
  }))

  return <LiveContext value={{ status, ...value }}>{children}</LiveContext>
}

function useLiveContext(): LiveState {
  const value = useContext(LiveContext)
  if (!value) throw new Error('useLive must be used inside <LiveProvider>')
  return value
}

export function useLiveStatus(): LiveStatus {
  return useLiveContext().status
}

/** Run `handler` for every live message while the component is mounted. */
export function useLive(handler: Handler): void {
  const { subscribe } = useLiveContext()
  const latest = useRef(handler)
  useEffect(() => {
    latest.current = handler
  })
  useEffect(
    () =>
      subscribe((message) => {
        latest.current(message)
      }),
    [subscribe],
  )
}
