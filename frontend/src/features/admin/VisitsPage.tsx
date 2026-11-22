import { Plate } from '@/components/ui/plate'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { formatDateTime, formatMinutes, titleCase } from '@/lib/format'

import { VisitStatusBadge } from '../shared/VisitStatusBadge'
import { ResourcePage, type ResourceConfig } from './ResourcePage'

const STATUSES: Schemas['VisitStatus'][] = [
  'pending_approval',
  'approved',
  'inside',
  'overstayed',
  'escalated',
  'exited',
  'denied',
  'expired',
]

const visits: ResourceConfig<Schemas['VisitRead']> = {
  key: 'visits',
  title: 'Visits',
  singular: 'Visit',
  description: 'Every visitor, newest first. Phone numbers are masked.',
  search: 'Search by visitor name or plate',
  filter: { label: 'Status', options: STATUSES.map((s) => ({ value: s, label: titleCase(s) })) },
  list: ({ q, filter, limit, offset }) =>
    unwrap(
      api.GET('/api/v1/visits', {
        params: {
          query: { q, limit, offset, status: filter as Schemas['VisitStatus'] | undefined },
        },
      }),
    ),
  columns: [
    {
      header: 'Visitor',
      cell: (v) => (
        <div>
          <p className="font-medium">{v.visitor_name ?? 'Guest pass'}</p>
          <p className="text-xs text-muted tabular">{v.visitor_phone ?? ''}</p>
        </div>
      ),
    },
    { header: 'Flat', cell: (v) => <span className="tabular">{v.flat_label}</span> },
    {
      header: 'Type',
      cell: (v) => (
        <span>
          {titleCase(v.category)}
          {v.purpose ? <span className="block text-xs text-muted">{v.purpose}</span> : null}
        </span>
      ),
    },
    {
      header: 'Vehicle',
      cell: (v) =>
        v.plate_normalized ? (
          <Plate plate={v.plate_normalized} size="sm" />
        ) : (
          <span className="text-muted">On foot</span>
        ),
    },
    {
      header: 'Entered',
      cell: (v) => (v.entered_at ? formatDateTime(v.entered_at) : '—'),
      className: 'text-muted tabular',
    },
    {
      header: 'Stayed',
      cell: (v) =>
        v.entered_at && v.exited_at
          ? formatMinutes(
              (new Date(v.exited_at).getTime() - new Date(v.entered_at).getTime()) / 60_000,
            )
          : '—',
      className: 'tabular',
    },
    { header: 'Status', cell: (v) => <VisitStatusBadge status={v.status} /> },
  ],
}

export const VisitsPage = () => <ResourcePage config={visits} />
