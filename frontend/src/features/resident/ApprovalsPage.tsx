import { useQueryClient } from '@tanstack/react-query'
import { BellRing, CarFront } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Plate } from '@/components/ui/plate'
import { SkeletonRows } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/ui/states'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { formatCountdown, formatMinutes, formatTime, titleCase } from '@/lib/format'
import { useApprovals, useVisits, type Approval } from '@/lib/queries'
import { useNow } from '@/lib/useNow'
import { useMutation } from '@tanstack/react-query'

type ApprovalPage = Schemas['Page_ApprovalRead_']

function ApprovalCard({ approval, now }: { approval: Approval; now: number }) {
  const client = useQueryClient()
  const { visit } = approval
  const left = new Date(approval.expires_at).getTime() - now

  // Optimistic: the card disappears as soon as you tap; it comes back if the call fails.
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'deny') =>
      unwrap(
        api.POST('/api/v1/approvals/{approval_id}/decision', {
          params: { path: { approval_id: approval.id } },
          body: { decision },
        }),
      ),
    onMutate: async () => {
      await client.cancelQueries({ queryKey: ['approvals', 'pending'] })
      const previous = client.getQueryData<ApprovalPage>(['approvals', 'pending'])
      client.setQueryData<ApprovalPage>(['approvals', 'pending'], (page) =>
        page
          ? {
              ...page,
              items: page.items.filter((a) => a.id !== approval.id),
              total: page.total - 1,
            }
          : page,
      )
      return { previous }
    },
    onError: (error, _decision, context) => {
      client.setQueryData(['approvals', 'pending'], context?.previous)
      toast.error(error.message)
    },
    onSuccess: (_result, decision) => {
      const name = visit.visitor_name ?? 'Your visitor'
      toast.success(decision === 'approve' ? `${name} can come in` : `${name} was turned away`)
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['approvals'] })
      void client.invalidateQueries({ queryKey: ['visits'] })
    },
  })

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1">
          <p className="text-lg font-semibold">{visit.visitor_name ?? 'Visitor'}</p>
          <p className="text-sm text-muted">
            {titleCase(visit.category)} for {visit.flat_label}
            {visit.purpose ? `: ${visit.purpose}` : ''}
          </p>
          {visit.visitor_phone ? (
            <p className="text-sm text-muted tabular">{visit.visitor_phone}</p>
          ) : null}
        </div>
        <Badge
          tone={left < 30_000 ? 'warn' : 'accent'}
          className="text-sm tabular"
          aria-label={`${formatCountdown(left)} left to answer`}
        >
          {formatCountdown(left)}
        </Badge>
      </div>
      {visit.plate_normalized ? (
        <div className="mt-3">
          <Plate plate={visit.plate_normalized} size="md" />
        </div>
      ) : null}
      <div className="mt-4 grid grid-cols-2 gap-2">
        <Button
          size="lg"
          variant="danger-outline"
          disabled={decide.isPending}
          onClick={() => {
            decide.mutate('deny')
          }}
        >
          Turn away
        </Button>
        <Button
          size="lg"
          variant="approve"
          disabled={decide.isPending}
          onClick={() => {
            decide.mutate('approve')
          }}
        >
          Approve
        </Button>
      </div>
      <p className="mt-3 text-xs text-muted">If you don’t answer in time, the guard decides.</p>
    </Card>
  )
}

function InsideNow() {
  const inside = useVisits({ inside: true, limit: 20 })
  const now = useNow(30_000)
  const items = inside.data?.items ?? []
  if (items.length === 0) return null
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-base font-semibold">Your visitors inside</h2>
      <div className="grid gap-2">
        {items.map((visit) => {
          const left = visit.expected_exit_at
            ? new Date(visit.expected_exit_at).getTime() - now
            : null
          return (
            <Card key={visit.id} className="flex items-center justify-between gap-3 p-3">
              <div>
                <p className="font-medium">{visit.visitor_name}</p>
                <p className="text-xs text-muted">
                  In since {visit.entered_at ? formatTime(visit.entered_at) : '—'}
                </p>
              </div>
              {left !== null ? (
                <Badge tone={left < 0 ? 'warn' : 'neutral'} className="tabular">
                  {left < 0
                    ? `${formatMinutes(-left / 60_000)} over`
                    : `${formatMinutes(left / 60_000)} left`}
                </Badge>
              ) : null}
            </Card>
          )
        })}
      </div>
    </section>
  )
}

export function ApprovalsPage() {
  const pending = useApprovals('pending')
  const now = useNow(1000)
  const items = (pending.data?.items ?? []).filter(
    (a) => new Date(a.expires_at).getTime() > now - 2000,
  )

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Approvals</h1>
      {pending.isLoading ? <SkeletonRows rows={2} /> : null}
      {pending.isError ? (
        <ErrorState error={pending.error} onRetry={() => void pending.refetch()} />
      ) : null}
      {pending.data && items.length === 0 ? (
        <EmptyState icon={BellRing} title="Nobody is waiting at the gate">
          When a visitor arrives for your flat, they appear here with Approve and Turn away buttons.
          Expecting someone? Create a guest pass and they’ll be let straight in.
        </EmptyState>
      ) : null}
      <div className="grid gap-3">
        {items.map((approval) => (
          <ApprovalCard key={approval.id} approval={approval} now={now} />
        ))}
      </div>
      <InsideNow />
      {pending.data && items.length === 0 ? null : (
        <p className="mt-6 flex items-center gap-2 text-xs text-muted">
          <CarFront className="size-4" aria-hidden="true" /> Approved visitors are let in by the
          guard.
        </p>
      )}
    </div>
  )
}
