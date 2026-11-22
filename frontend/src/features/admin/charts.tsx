/**
 * Dashboard charts (Recharts). Rules from the dataviz checklist: one axis, thin marks with
 * 4 px rounded ends on a single baseline, recessive grid, a legend whenever there are two
 * series, a hover tooltip on every mark, and a table view of the same numbers.
 * Series colours (--series-1/2) were validated for colour-blind separation in both themes.
 */
import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'

import { formatDay, formatMinutes, titleCase } from '@/lib/format'
import type { Schemas } from '@/lib/api/client'

type TipProps = TooltipContentProps

const AXIS = { fontSize: 12, fill: 'var(--muted)' }

function hourLabel(hour: number): string {
  if (hour === 0) return '12 am'
  if (hour === 12) return '12 pm'
  return hour < 12 ? `${hour.toString()} am` : `${(hour - 12).toString()} pm`
}

function TooltipBox({
  title,
  rows,
}: {
  title: string
  rows: { label: string; value: string; color?: string }[]
}) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-text">{title}</p>
      {rows.map((row) => (
        <p key={row.label} className="flex items-center gap-2 text-muted">
          {row.color ? (
            <span
              className="size-2 rounded-sm"
              style={{ background: row.color }}
              aria-hidden="true"
            />
          ) : null}
          {row.label}
          <span className="ml-auto pl-4 font-medium text-text tabular">{row.value}</span>
        </p>
      ))}
    </div>
  )
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-4 text-xs text-muted">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span
            className="size-2.5 rounded-sm"
            style={{ background: item.color }}
            aria-hidden="true"
          />
          {item.label}
        </li>
      ))}
    </ul>
  )
}

/** The same numbers as a table, for screen readers and anyone who prefers it. */
export function TableView({
  caption,
  head,
  rows,
}: {
  caption: string
  head: string[]
  rows: ReactNode[][]
}) {
  return (
    <details className="mt-3 text-sm">
      <summary className="cursor-pointer text-xs text-muted hover:text-text">View as table</summary>
      <table className="mt-2 w-full text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {head.map((h) => (
              <th
                key={h}
                scope="col"
                className="border-b border-border py-1.5 font-medium text-muted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="border-b border-border py-1.5 tabular">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  )
}

export function BusiestHoursChart({ hours }: { hours: Schemas['HourCountRead'][] }) {
  const data = hours.map((h) => ({ ...h, label: hourLabel(h.hour) }))
  return (
    <div>
      <Legend
        items={[
          { label: 'Residents', color: 'var(--series-1)' },
          { label: 'Visitors', color: 'var(--series-2)' },
        ]}
      />
      <div
        className="mt-3 h-56"
        role="img"
        aria-label="Gate entries per hour of the day, residents and visitors"
      >
        <ResponsiveContainer>
          <BarChart
            data={data}
            margin={{ top: 4, right: 0, bottom: 0, left: -18 }}
            barCategoryGap={2}
          >
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} interval={2} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: 'var(--surface-2)' }}
              content={({ active, payload, label }: TipProps) =>
                active && payload.length ? (
                  <TooltipBox
                    title={String(label)}
                    rows={[
                      {
                        label: 'Residents',
                        value: String(payload[0]?.value ?? 0),
                        color: 'var(--series-1)',
                      },
                      {
                        label: 'Visitors',
                        value: String(payload[1]?.value ?? 0),
                        color: 'var(--series-2)',
                      },
                    ]}
                  />
                ) : null
              }
            />
            <Bar
              dataKey="residents"
              stackId="a"
              fill="var(--series-1)"
              maxBarSize={24}
              stroke="var(--surface)"
              strokeWidth={1}
            />
            <Bar
              dataKey="visitors"
              stackId="a"
              fill="var(--series-2)"
              maxBarSize={24}
              radius={[4, 4, 0, 0]}
              stroke="var(--surface)"
              strokeWidth={1}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView
        caption="Gate entries per hour"
        head={['Hour', 'Residents', 'Visitors']}
        rows={data.map((d) => [d.label, d.residents, d.visitors])}
      />
    </div>
  )
}

export function DailyVisitsChart({ days }: { days: Schemas['DayCountRead'][] }) {
  const data = days.map((d) => ({ ...d, label: formatDay(d.day) }))
  return (
    <div>
      <div className="h-56" role="img" aria-label="Visits per day">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} minTickGap={12} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: 'var(--surface-2)' }}
              content={({ active, payload, label }: TipProps) =>
                active && payload.length ? (
                  <TooltipBox
                    title={String(label)}
                    rows={[{ label: 'Visits', value: String(payload[0]?.value ?? 0) }]}
                  />
                ) : null
              }
            />
            <Bar dataKey="visits" fill="var(--series-1)" maxBarSize={24} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView
        caption="Visits per day"
        head={['Day', 'Visits']}
        rows={data.map((d) => [d.label, d.visits])}
      />
    </div>
  )
}

export function CategoryChart({ categories }: { categories: Schemas['CategoryStatRead'][] }) {
  const data = categories.map((c) => ({
    ...c,
    label: titleCase(c.category),
    tip: `${c.visits.toString()}${c.average_minutes !== null ? `, avg ${formatMinutes(c.average_minutes)}` : ''}`,
  }))
  return (
    <div>
      <div className="h-48" role="img" aria-label="Visits by type, with the average length of each">
        <ResponsiveContainer>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 0, right: 110, bottom: 0, left: 8 }}
          >
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="label"
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              width={64}
            />
            <Tooltip
              cursor={{ fill: 'var(--surface-2)' }}
              content={({ active, payload }: TipProps) => {
                const row = payload[0]?.payload as (typeof data)[number] | undefined
                return active && row ? (
                  <TooltipBox
                    title={row.label}
                    rows={[
                      { label: 'Visits', value: row.visits.toString() },
                      {
                        label: 'Average length',
                        value:
                          row.average_minutes !== null ? formatMinutes(row.average_minutes) : '—',
                      },
                    ]}
                  />
                ) : null
              }}
            />
            <Bar dataKey="visits" fill="var(--series-1)" barSize={18} radius={[0, 4, 4, 0]}>
              <LabelList
                dataKey="tip"
                position="right"
                style={{ fontSize: 12, fill: 'var(--text)' }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TableView
        caption="Visits by type"
        head={['Type', 'Visits', 'Average length']}
        rows={data.map((d) => [
          d.label,
          d.visits,
          d.average_minutes !== null ? formatMinutes(d.average_minutes) : '—',
        ])}
      />
    </div>
  )
}
