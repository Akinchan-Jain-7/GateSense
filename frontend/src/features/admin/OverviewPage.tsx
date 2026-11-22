import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/ui/states'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api, unwrap } from '@/lib/api/client'
import { formatAgo, formatMinutes } from '@/lib/format'

import { BusiestHoursChart, CategoryChart, DailyVisitsChart } from './charts'
import { PageHeader } from './PageHeader'

const WINDOWS = [7, 14, 30] as const

function Stat({
  label,
  value,
  detail,
  children,
}: {
  label: string
  value: string
  detail?: ReactNode
  children?: ReactNode
}) {
  return (
    <Card className="p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular">{value}</p>
      {detail ? <p className="mt-1 text-xs text-muted">{detail}</p> : null}
      {children}
    </Card>
  )
}

function ParkingMeter({ used, slots }: { used: number; slots: number }) {
  const share = slots > 0 ? Math.min(1, used / slots) : 0
  return (
    <div
      className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={slots}
      aria-valuenow={used}
      aria-label="Visitor parking in use"
    >
      <div
        className={share >= 0.9 ? 'h-full rounded-full bg-warn' : 'h-full rounded-full bg-series-1'}
        style={{ width: `${(share * 100).toString()}%` }}
      />
    </div>
  )
}

export function OverviewPage() {
  const [days, setDays] = useState<number>(14)
  const overview = useQuery({
    queryKey: ['analytics', days],
    queryFn: () => unwrap(api.GET('/api/v1/analytics/overview', { params: { query: { days } } })),
    refetchInterval: 60_000,
  })
  const data = overview.data

  return (
    <div>
      <PageHeader title="Overview" description="Hours and days are in Indian time.">
        <Tabs
          value={String(days)}
          onValueChange={(v) => {
            setDays(Number(v))
          }}
        >
          <TabsList aria-label="Time range">
            {WINDOWS.map((w) => (
              <TabsTrigger key={w} value={String(w)}>
                {w.toString()} days
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </PageHeader>

      {overview.isError ? (
        <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {data ? (
          <>
            <Stat
              label="Visits"
              value={data.visits.toLocaleString('en-IN')}
              detail={`in the last ${days.toString()} days`}
            />
            <Stat
              label="Average visit"
              value={
                data.average_visit_minutes !== null
                  ? formatMinutes(data.average_visit_minutes)
                  : '—'
              }
              detail="entry to exit"
            />
            <Stat
              label="Overstay rate"
              value={
                data.overstay_rate !== null ? `${(data.overstay_rate * 100).toFixed(1)}%` : '—'
              }
              detail={`${data.overstayed_visits.toString()} visits went past their limit`}
            />
            <Stat
              label="Vehicles inside now"
              value={data.vehicles_inside.toString()}
              detail={`${data.residents_inside.toString()} residents, ${data.visitors_inside.toString()} visitors`}
            />
            <Stat
              label="Visitor parking"
              value={`${data.visitor_vehicles_inside.toString()} of ${data.visitor_parking_slots.toString()}`}
              detail="spaces in use"
            >
              <ParkingMeter
                used={data.visitor_vehicles_inside}
                slots={data.visitor_parking_slots}
              />
            </Stat>
          </>
        ) : (
          Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)
        )}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Busiest hours at the gate</CardTitle>
            <span className="text-xs text-muted">entry-lane reads</span>
          </CardHeader>
          <CardContent>
            {data ? (
              <BusiestHoursChart hours={data.busiest_hours} />
            ) : (
              <Skeleton className="h-64" />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Visits per day</CardTitle>
          </CardHeader>
          <CardContent>
            {data ? <DailyVisitsChart days={data.daily_visits} /> : <Skeleton className="h-64" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Visits by type</CardTitle>
            <span className="text-xs text-muted">count and average length</span>
          </CardHeader>
          <CardContent>
            {data ? <CategoryChart categories={data.categories} /> : <Skeleton className="h-48" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Frequent visitors</CardTitle>
          </CardHeader>
          {data ? (
            data.frequent_visitors.length === 0 ? (
              <CardContent>
                <p className="text-sm text-muted">No visits in this period yet.</p>
              </CardContent>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Visitor</Th>
                    <Th className="text-right">Visits</Th>
                    <Th>Flats</Th>
                    <Th>Last seen</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.frequent_visitors.map((v) => (
                    <Tr key={v.visitor_id}>
                      <Td>
                        <p className="font-medium">{v.name}</p>
                        <p className="text-xs text-muted tabular">{v.phone_masked}</p>
                      </Td>
                      <Td className="text-right tabular">{v.visits.toString()}</Td>
                      <Td className="text-muted">
                        {v.flats.length > 3
                          ? `${v.flats.length.toString()} flats`
                          : v.flats.join(', ')}
                      </Td>
                      <Td className="text-muted">{formatAgo(v.last_visit_at)}</Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            )
          ) : (
            <CardContent>
              <Skeleton className="h-40" />
            </CardContent>
          )}
        </Card>
      </div>
    </div>
  )
}
