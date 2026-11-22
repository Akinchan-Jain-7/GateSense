import { Badge, type BadgeTone } from '@/components/ui/badge'
import type { VisitStatus } from '@/lib/queries'

const STATUS: Record<VisitStatus, { label: string; tone: BadgeTone }> = {
  pending_approval: { label: 'Waiting for approval', tone: 'accent' },
  approved: { label: 'Approved', tone: 'ok' },
  inside: { label: 'Inside', tone: 'ok' },
  overstayed: { label: 'Over time', tone: 'warn' },
  escalated: { label: 'Guard calling', tone: 'warn' },
  exited: { label: 'Left', tone: 'neutral' },
  denied: { label: 'Turned away', tone: 'danger' },
  expired: { label: 'Expired', tone: 'neutral' },
}

export function VisitStatusBadge({ status }: { status: VisitStatus }) {
  const { label, tone } = STATUS[status]
  return <Badge tone={tone}>{label}</Badge>
}
