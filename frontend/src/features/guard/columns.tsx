import {
  ArrowDownLeft,
  ArrowUpRight,
  BellOff,
  CarFront,
  Check,
  Clock,
  Hourglass,
  PencilLine,
  Phone,
  ShieldAlert,
  UserPlus,
} from 'lucide-react'
import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Badge, type BadgeTone } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Plate } from '@/components/ui/plate'
import { SkeletonRows } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/ui/states'
import { api, unwrap } from '@/lib/api/client'
import { cn } from '@/lib/cn'
import { formatCountdown, formatMinutes, formatTime } from '@/lib/format'
import { cleanPlateInput } from '@/lib/plates'
import {
  useAction,
  useAlerts,
  useApprovals,
  useEscalations,
  useGateEvents,
  useVisits,
  type Approval,
  type Escalation,
  type GateEvent,
  type Visit,
} from '@/lib/queries'
import { useNow } from '@/lib/useNow'

import type { RegisterPrefill } from './RegisterVisitorDialog'
import { Snapshot } from './Snapshot'

const MATCH_TONE: Record<GateEvent['match_result'], BadgeTone> = {
  resident: 'ok',
  guest_pass: 'ok',
  visitor: 'accent',
  watchlist: 'danger',
  unknown: 'neutral',
  low_confidence: 'warn',
}

function Column({
  title,
  count,
  children,
  className,
}: {
  title: string
  count?: number
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex min-h-0 flex-col', className)} aria-label={title}>
      <h2 className="flex items-center gap-2 px-1 pb-3 text-base font-semibold">
        {title}
        {count ? (
          <span className="rounded-full bg-surface-2 px-2 text-sm text-muted tabular">
            {count.toString()}
          </span>
        ) : null}
      </h2>
      <div className="grid min-h-0 content-start gap-2 overflow-y-auto pb-4">{children}</div>
    </section>
  )
}

function Item({ children, tone }: { children: ReactNode; tone?: 'warn' | 'danger' | 'accent' }) {
  return (
    <article
      className={cn(
        'rounded-xl border bg-surface p-3.5',
        tone === 'danger' && 'border-danger/50 bg-danger-soft',
        tone === 'warn' && 'border-warn/50',
        tone === 'accent' && 'border-accent/40',
        !tone && 'border-border',
      )}
    >
      {children}
    </article>
  )
}

function VehicleLine({ plate, raw }: { plate: string | null | undefined; raw?: string }) {
  if (plate) return <Plate plate={plate} size="lg" />
  return (
    <span className="inline-flex h-11 items-center rounded-[4px] border-[1.5px] border-dashed border-border-strong px-3 font-plate text-lg text-muted">
      {raw ?? '—'}
    </span>
  )
}

// --- Arrivals -----------------------------------------------------------------------

function ReviewActions({ event }: { event: GateEvent }) {
  const { t } = useTranslation()
  const [fixing, setFixing] = useState(false)
  const [plate, setPlate] = useState(event.plate_normalized ?? event.plate_raw)
  const review = useAction(
    (value: string) =>
      unwrap(
        api.POST('/api/v1/gate-events/{event_id}/review', {
          params: { path: { event_id: event.id } },
          body: { action: 'correct', plate: value },
        }),
      ),
    { invalidate: [['gate-events'], ['review-queue'], ['visits']] },
  )

  function save(e: FormEvent) {
    e.preventDefault()
    review.mutate(cleanPlateInput(plate))
  }

  return (
    <div className="mt-3 rounded-lg bg-warn-soft p-3">
      <p className="text-sm font-medium text-warn">
        {t('arrivals.needsCheck')}{' '}
        <span className="font-normal tabular">
          ({t('arrivals.confidence', { value: Math.round(event.confidence * 100) })})
        </span>
      </p>
      {fixing ? (
        <form className="mt-2 flex gap-2" onSubmit={save}>
          <Input
            aria-label={t('arrivals.correctLabel')}
            autoFocus
            className="h-12 font-plate text-lg uppercase"
            value={plate}
            onChange={(e) => {
              setPlate(e.target.value)
            }}
          />
          <Button type="submit" size="xl" disabled={review.isPending}>
            {t('arrivals.save')}
          </Button>
        </form>
      ) : (
        <div className="mt-2 grid grid-cols-2 gap-2">
          {event.plate_normalized ? (
            <Button
              size="xl"
              variant="secondary"
              disabled={review.isPending}
              onClick={() => {
                review.mutate(event.plate_normalized ?? '')
              }}
            >
              <Check /> {t('arrivals.confirm')}
            </Button>
          ) : null}
          <Button
            size="xl"
            variant="secondary"
            className={event.plate_normalized ? '' : 'col-span-2'}
            onClick={() => {
              setFixing(true)
            }}
          >
            <PencilLine /> {t('arrivals.correct')}
          </Button>
        </div>
      )}
    </div>
  )
}

export function ArrivalsColumn({
  onRegister,
  className,
}: {
  onRegister: (prefill: RegisterPrefill) => void
  className?: string
}) {
  const { t, i18n } = useTranslation()
  const events = useGateEvents(30)
  const visits = useVisits({ limit: 100 })
  const now = useNow(10_000)
  const visitById = useMemo(
    () => new Map((visits.data?.items ?? []).map((v) => [v.id, v])),
    [visits.data],
  )

  return (
    <Column title={t('console.arrivals')} className={className}>
      {events.isLoading ? <SkeletonRows rows={5} /> : null}
      {events.isError ? (
        <ErrorState error={events.error} onRetry={() => void events.refetch()} />
      ) : null}
      {events.data?.items.length === 0 ? (
        <EmptyState icon={CarFront} title={t('arrivals.empty')} />
      ) : null}
      {events.data?.items.map((event) => {
        const visit = event.visit_id ? visitById.get(event.visit_id) : undefined
        const fresh = now - new Date(event.received_at).getTime() < 15_000
        const unresolved = event.needs_review && !event.reviewed_at
        const plateText = event.plate_normalized ?? event.plate_raw
        return (
          <div key={event.id} className={fresh ? 'animate-arrive' : undefined}>
            <Item
              tone={event.match_result === 'watchlist' ? 'danger' : unresolved ? 'warn' : undefined}
            >
              <div className="flex items-start gap-3">
                {event.has_snapshot ? (
                  <Snapshot
                    eventId={event.id}
                    alt={t('arrivals.snapshot', { plate: plateText })}
                    className="h-14 w-20 shrink-0"
                  />
                ) : null}
                <div className="grid min-w-0 flex-1 gap-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <VehicleLine plate={event.plate_normalized} raw={event.plate_raw} />
                    <span className="text-sm text-muted tabular">
                      {formatTime(event.captured_at, i18n.language)}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1 text-sm font-medium">
                      {event.direction === 'entry' ? (
                        <ArrowDownLeft className="size-4 text-ok" aria-hidden="true" />
                      ) : (
                        <ArrowUpRight className="size-4 text-muted" aria-hidden="true" />
                      )}
                      {t(`lane.${event.direction}`)}
                    </span>
                    <Badge tone={MATCH_TONE[event.match_result]}>
                      {t(`match.${event.match_result}`)}
                    </Badge>
                    {visit ? (
                      <span className="truncate text-sm text-muted">
                        {visit.visitor_name ?? ''} {visit.flat_label}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
              {unresolved ? <ReviewActions event={event} /> : null}
              {!unresolved &&
              event.match_result === 'unknown' &&
              event.direction === 'entry' &&
              !event.visit_id ? (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-muted">{t('arrivals.unknownHint')}</p>
                  <Button
                    size="lg"
                    onClick={() => {
                      onRegister({ plate: event.plate_normalized ?? '', gateEventId: event.id })
                    }}
                  >
                    <UserPlus /> {t('console.registerVisitor')}
                  </Button>
                </div>
              ) : null}
            </Item>
          </div>
        )
      })}
    </Column>
  )
}

// --- Waiting for a decision ---------------------------------------------------------

function VisitSummary({ visit }: { visit: Visit }) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-2">
      {visit.plate_normalized ? <Plate plate={visit.plate_normalized} size="lg" /> : null}
      <div>
        <p className="text-base font-semibold">{visit.visitor_name ?? '—'}</p>
        <p className="text-sm text-muted">
          {t(`category.${visit.category}`)}, {visit.flat_label}
          {visit.purpose ? `: ${visit.purpose}` : ''}
        </p>
      </div>
    </div>
  )
}

function Countdown({ approval, now }: { approval: Approval; now: number }) {
  const total = new Date(approval.expires_at).getTime() - new Date(approval.requested_at).getTime()
  const left = new Date(approval.expires_at).getTime() - now
  const share = Math.max(0, Math.min(1, left / total))
  return (
    <div className="mt-3 grid gap-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="inline-flex items-center gap-1.5 text-accent">
          <Hourglass className="size-4" aria-hidden="true" />
          <WaitingLabel />
        </span>
        <span className="font-medium tabular" aria-live="off">
          {formatCountdown(left)}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-1000 ease-linear"
          style={{ width: `${(share * 100).toString()}%` }}
        />
      </div>
    </div>
  )
}

function WaitingLabel() {
  const { t } = useTranslation()
  return <>{t('waiting.askingResident')}</>
}

export function WaitingColumn({ className }: { className?: string }) {
  const { t } = useTranslation()
  const approvals = useApprovals()
  const approved = useVisits({ status: 'approved', limit: 50 })
  const now = useNow(1000)

  const decide = useAction(
    ({ visitId, decision }: { visitId: string; decision: 'approve' | 'deny' }) =>
      unwrap(
        api.POST('/api/v1/visits/{visit_id}/decision', {
          params: { path: { visit_id: visitId } },
          body: { decision },
        }),
      ),
    { invalidate: [['approvals'], ['visits']] },
  )
  const enter = useAction(
    (visitId: string) =>
      unwrap(
        api.POST('/api/v1/visits/{visit_id}/enter', { params: { path: { visit_id: visitId } } }),
      ),
    { invalidate: [['visits']] },
  )

  const items = approvals.data?.items ?? []
  const pending = items.filter((a) => a.status === 'pending')
  const timedOut = items.filter(
    (a) => a.status === 'timed_out' && a.visit.status === 'pending_approval',
  )
  const arriving = approved.data?.items ?? []
  const count = pending.length + timedOut.length + arriving.length

  return (
    <Column title={t('console.waiting')} count={count} className={className}>
      {approvals.isLoading ? <SkeletonRows rows={3} /> : null}
      {approvals.isError ? (
        <ErrorState error={approvals.error} onRetry={() => void approvals.refetch()} />
      ) : null}
      {approvals.data && count === 0 ? (
        <EmptyState icon={Clock} title={t('waiting.empty')} />
      ) : null}

      {timedOut.map((approval) => (
        <Item key={approval.id} tone="warn">
          <p className="mb-3 text-sm font-semibold text-warn">{t('waiting.noAnswer')}</p>
          <VisitSummary visit={approval.visit} />
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Button
              size="xl"
              variant="approve"
              disabled={decide.isPending}
              onClick={() => {
                decide.mutate({ visitId: approval.visit.id, decision: 'approve' })
              }}
            >
              {t('waiting.admit')}
            </Button>
            <Button
              size="xl"
              variant="danger-outline"
              disabled={decide.isPending}
              onClick={() => {
                decide.mutate({ visitId: approval.visit.id, decision: 'deny' })
              }}
            >
              {t('waiting.turnAway')}
            </Button>
          </div>
        </Item>
      ))}

      {pending.map((approval) => (
        <Item key={approval.id} tone="accent">
          <VisitSummary visit={approval.visit} />
          <Countdown approval={approval} now={now} />
        </Item>
      ))}

      {arriving.map((visit) => (
        <Item key={visit.id}>
          <p className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-ok">
            <Check className="size-4" aria-hidden="true" /> {t('waiting.approvedArriving')}
          </p>
          <VisitSummary visit={visit} />
          <Button
            size="xl"
            variant="secondary"
            className="mt-3 w-full"
            disabled={enter.isPending}
            onClick={() => {
              enter.mutate(visit.id)
            }}
          >
            {t('waiting.markEntered')}
          </Button>
        </Item>
      ))}
    </Column>
  )
}

// --- Alerts and calls ---------------------------------------------------------------

function CallTask({ task, now }: { task: Escalation; now: number }) {
  const { t } = useTranslation()
  const resolve = useAction(
    (outcome: 'reached' | 'not_reached' | 'vehicle_left') =>
      unwrap(
        api.POST('/api/v1/escalations/{task_id}/resolve', {
          params: { path: { task_id: task.id } },
          body: { outcome },
        }),
      ),
    {
      invalidate: [['escalations'], ['visits']],
      success: (_, outcome) =>
        t(
          outcome === 'reached'
            ? 'outcome.reached'
            : outcome === 'not_reached'
              ? 'outcome.notReached'
              : 'outcome.vehicleLeft',
        ),
    },
  )
  const expected = task.visit.expected_exit_at
    ? new Date(task.visit.expected_exit_at).getTime()
    : now
  return (
    <Item tone="warn">
      <p className="flex items-center gap-1.5 text-base font-semibold">
        <Phone className="size-4 text-warn" aria-hidden="true" />
        {t('alerts.callResident', { flat: task.visit.flat_label })}
      </p>
      <p className="mt-1 text-sm text-warn tabular">
        {t('alerts.overBy', { time: formatMinutes((now - expected) / 60_000) })}
      </p>
      <div className="mt-3">
        <VisitSummary visit={task.visit} />
      </div>
      {task.contacts.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {task.contacts.map((contact) =>
            contact.phone ? (
              <Button key={contact.phone} asChild size="xl" variant="primary">
                <a href={`tel:${contact.phone}`}>
                  <Phone /> {contact.name}
                </a>
              </Button>
            ) : null,
          )}
        </div>
      ) : null}
      <div className="mt-2 grid grid-cols-3 gap-2">
        <Button
          size="lg"
          variant="secondary"
          className="h-14 whitespace-normal"
          disabled={resolve.isPending}
          onClick={() => {
            resolve.mutate('reached')
          }}
        >
          {t('alerts.reached')}
        </Button>
        <Button
          size="lg"
          variant="secondary"
          className="h-14 whitespace-normal"
          disabled={resolve.isPending}
          onClick={() => {
            resolve.mutate('not_reached')
          }}
        >
          {t('alerts.notReached')}
        </Button>
        <Button
          size="lg"
          variant="secondary"
          className="h-14 whitespace-normal"
          disabled={resolve.isPending}
          onClick={() => {
            resolve.mutate('vehicle_left')
          }}
        >
          {t('alerts.vehicleLeft')}
        </Button>
      </div>
    </Item>
  )
}

export function AlertsColumn({ className }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const alerts = useAlerts(false)
  const tasks = useEscalations('open')
  const events = useGateEvents(30)
  const now = useNow(30_000)
  const eventById = useMemo(
    () => new Map((events.data?.items ?? []).map((e) => [e.id, e])),
    [events.data],
  )
  const acknowledge = useAction(
    (alertId: string) =>
      unwrap(
        api.POST('/api/v1/alerts/{alert_id}/acknowledge', {
          params: { path: { alert_id: alertId } },
        }),
      ),
    { invalidate: [['alerts']] },
  )

  const alertItems = alerts.data?.items ?? []
  const taskItems = tasks.data?.items ?? []
  const count = alertItems.length + taskItems.length

  return (
    <Column title={t('console.alerts')} count={count} className={className}>
      {alerts.isLoading || tasks.isLoading ? <SkeletonRows rows={2} /> : null}
      {alerts.isError ? (
        <ErrorState error={alerts.error} onRetry={() => void alerts.refetch()} />
      ) : null}
      {alerts.data && tasks.data && count === 0 ? (
        <EmptyState icon={BellOff} title={t('alerts.empty')} />
      ) : null}
      {alertItems.map((alert) => {
        const event = alert.gate_event_id ? eventById.get(alert.gate_event_id) : undefined
        return (
          <Item key={alert.id} tone="danger">
            <p className="flex items-center gap-1.5 text-base font-semibold text-danger">
              <ShieldAlert className="size-5" aria-hidden="true" />
              {t('alerts.watchlist')}
            </p>
            {event?.plate_normalized ? (
              <div className="mt-3">
                <Plate plate={event.plate_normalized} size="lg" />
              </div>
            ) : null}
            <p className="mt-2 text-sm text-text">{alert.message}</p>
            <p className="mt-1 text-xs text-muted tabular">
              {formatTime(alert.created_at, i18n.language)}
            </p>
            <Button
              size="xl"
              variant="secondary"
              className="mt-3 w-full"
              disabled={acknowledge.isPending}
              onClick={() => {
                acknowledge.mutate(alert.id)
              }}
            >
              {t('alerts.seen')}
            </Button>
          </Item>
        )
      })}
      {taskItems.map((task) => (
        <CallTask key={task.id} task={task} now={now} />
      ))}
    </Column>
  )
}

// --- Inside now ---------------------------------------------------------------------

export function InsideColumn({ className }: { className?: string }) {
  const { t } = useTranslation()
  const inside = useVisits({ inside: true, limit: 50 })
  const now = useNow(30_000)
  const exit = useAction(
    (visitId: string) =>
      unwrap(
        api.POST('/api/v1/visits/{visit_id}/exit', { params: { path: { visit_id: visitId } } }),
      ),
    { invalidate: [['visits'], ['escalations']] },
  )
  const items = inside.data?.items ?? []
  return (
    <Column title={t('console.insideNow')} count={items.length} className={className}>
      {inside.isLoading ? <SkeletonRows rows={2} /> : null}
      {inside.isError ? (
        <ErrorState error={inside.error} onRetry={() => void inside.refetch()} />
      ) : null}
      {inside.data && items.length === 0 ? (
        <EmptyState icon={CarFront} title={t('inside.empty')} />
      ) : null}
      {items.map((visit) => {
        const left = visit.expected_exit_at
          ? new Date(visit.expected_exit_at).getTime() - now
          : null
        const over = left !== null && left < 0
        return (
          <Item key={visit.id} tone={over ? 'warn' : undefined}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <VisitSummary visit={visit} />
              {left !== null ? (
                <Badge tone={over ? 'warn' : 'neutral'} className="text-sm tabular">
                  {over
                    ? t('inside.overBy', { time: formatMinutes(-left / 60_000) })
                    : t('inside.timeLeft', { time: formatMinutes(left / 60_000) })}
                </Badge>
              ) : null}
            </div>
            <Button
              size="lg"
              variant="secondary"
              className="mt-3 w-full"
              disabled={exit.isPending}
              onClick={() => {
                exit.mutate(visit.id)
              }}
            >
              {t('inside.markExit')}
            </Button>
          </Item>
        )
      })}
    </Column>
  )
}
