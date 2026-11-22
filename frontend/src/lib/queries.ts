/**
 * Data hooks shared by the three areas. Query keys start with the resource name
 * ('visits', 'approvals', ...) so a live message can invalidate a whole family at once
 * (see INVALIDATES in live.tsx).
 */
import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'

import { api, unwrap, type Schemas } from './api/client'

export type Visit = Schemas['VisitRead']
export type Approval = Schemas['ApprovalRead']
export type GateEvent = Schemas['GateEventRead']
export type Alert = Schemas['AlertRead']
export type Escalation = Schemas['EscalationRead']
export type GuestPass = Schemas['GuestPassRead']
export type Flat = Schemas['FlatRead']
export type VisitStatus = Schemas['VisitStatus']
export type VisitCategory = Schemas['VisitCategory']

export function useDemoInfo() {
  return useQuery({
    queryKey: ['demo'],
    queryFn: () => unwrap(api.GET('/api/v1/demo')),
    staleTime: Infinity,
    retry: false,
  })
}

export function useVisits(query: {
  status?: VisitStatus
  inside?: boolean
  q?: string
  limit?: number
  offset?: number
}) {
  return useQuery({
    queryKey: ['visits', query],
    queryFn: () => unwrap(api.GET('/api/v1/visits', { params: { query } })),
  })
}

export function useApprovals(status?: Schemas['ApprovalStatus']) {
  return useQuery({
    queryKey: ['approvals', status],
    queryFn: () =>
      unwrap(api.GET('/api/v1/approvals', { params: { query: { status, limit: 50 } } })),
  })
}

export function useAlerts(acknowledged = false) {
  return useQuery({
    queryKey: ['alerts', acknowledged],
    queryFn: () =>
      unwrap(api.GET('/api/v1/alerts', { params: { query: { acknowledged, limit: 50 } } })),
  })
}

export function useEscalations(status: Schemas['EscalationTaskStatus'] = 'open') {
  return useQuery({
    queryKey: ['escalations', status],
    queryFn: () =>
      unwrap(api.GET('/api/v1/escalations', { params: { query: { status, limit: 50 } } })),
  })
}

export function useGateEvents(limit = 30) {
  return useQuery({
    queryKey: ['gate-events', limit],
    queryFn: () => unwrap(api.GET('/api/v1/gate-events', { params: { query: { limit } } })),
  })
}

/** All flats, for pickers. Societies have tens to a few hundred flats. */
export function useAllFlats() {
  return useQuery({
    queryKey: ['flats', 'all'],
    queryFn: async () => {
      const flats: Flat[] = []
      for (let offset = 0; ; offset += 100) {
        const page = await unwrap(
          api.GET('/api/v1/flats', { params: { query: { limit: 100, offset } } }),
        )
        flats.push(...page.items)
        if (flats.length >= page.total || page.items.length === 0) return flats
      }
    },
    staleTime: 10 * 60_000,
  })
}

export function useVisitSettings() {
  return useQuery({
    queryKey: ['settings', 'visits'],
    queryFn: () => unwrap(api.GET('/api/v1/settings/visits')),
    staleTime: 5 * 60_000,
  })
}

/**
 * A mutation that shows a toast on success/failure and refreshes the given queries.
 * Errors from the API already have a readable message (see errorMessage in client.ts).
 */
export function useAction<TInput, TResult>(
  action: (input: TInput) => Promise<TResult>,
  {
    invalidate = [],
    success,
    onSuccess,
  }: {
    invalidate?: QueryKey[]
    success?: string | ((result: TResult, input: TInput) => string)
    onSuccess?: (result: TResult, input: TInput) => void
  } = {},
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: action,
    onSuccess: (result, input) => {
      for (const queryKey of invalidate) void client.invalidateQueries({ queryKey })
      if (success) toast.success(typeof success === 'string' ? success : success(result, input))
      onSuccess?.(result, input)
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : 'That didn’t work. Try again.')
    },
  })
}
