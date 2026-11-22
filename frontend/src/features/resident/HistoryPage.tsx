import { History } from 'lucide-react'
import { useState } from 'react'

import { Card } from '@/components/ui/card'
import { Pagination } from '@/components/ui/pagination'
import { Plate } from '@/components/ui/plate'
import { SkeletonRows } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/ui/states'
import { formatDateTime, formatMinutes, titleCase } from '@/lib/format'
import { useVisits } from '@/lib/queries'

import { VisitStatusBadge } from '../shared/VisitStatusBadge'

const PAGE = 20

export function HistoryPage() {
  const [offset, setOffset] = useState(0)
  const visits = useVisits({ limit: PAGE, offset })

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Visit history</h1>
      {visits.isLoading ? <SkeletonRows rows={5} /> : null}
      {visits.isError ? (
        <ErrorState error={visits.error} onRetry={() => void visits.refetch()} />
      ) : null}
      {visits.data?.items.length === 0 ? (
        <EmptyState icon={History} title="No visits yet">
          Everyone who visits your flat shows up here, with when they came and left.
        </EmptyState>
      ) : null}
      {visits.data && visits.data.items.length > 0 ? (
        <Card>
          <ul className="divide-y divide-border">
            {visits.data.items.map((visit) => {
              const minutes =
                visit.entered_at && visit.exited_at
                  ? (new Date(visit.exited_at).getTime() - new Date(visit.entered_at).getTime()) /
                    60_000
                  : null
              return (
                <li key={visit.id} className="grid gap-2 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-medium">{visit.visitor_name ?? 'Visitor'}</p>
                      <p className="text-xs text-muted">
                        {titleCase(visit.category)}
                        {visit.purpose ? `: ${visit.purpose}` : ''}
                      </p>
                    </div>
                    <VisitStatusBadge status={visit.status} />
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted tabular">
                    <span>
                      {formatDateTime(visit.entered_at ?? visit.created_at)}
                      {minutes !== null ? `, stayed ${formatMinutes(minutes)}` : ''}
                    </span>
                    {visit.plate_normalized ? (
                      <Plate plate={visit.plate_normalized} size="sm" />
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ul>
          <Pagination offset={offset} limit={PAGE} total={visits.data.total} onChange={setOffset} />
        </Card>
      ) : null}
    </div>
  )
}
