import { api, unwrap, type Schemas } from '@/lib/api/client'
import { formatDateTime, titleCase } from '@/lib/format'

import { ResourcePage, type ResourceConfig } from './ResourcePage'

const ENTITIES = ['flat', 'resident', 'vehicle', 'guard', 'gate', 'device', 'watchlist', 'settings']

function describeChange(value: unknown): string {
  if (Array.isArray(value) && value.length === 2) return `${String(value[0])} → ${String(value[1])}`
  if (value && typeof value === 'object' && 'from' in value && 'to' in value) {
    const change = value
    return `${String(change.from)} → ${String(change.to)}`
  }
  return String(value)
}

const audit: ResourceConfig<Schemas['AuditLogRead']> = {
  key: 'audit',
  title: 'Audit log',
  singular: 'Entry',
  description: 'Every change an admin made, newest first. Entries can’t be edited or deleted.',
  filter: { label: 'Record', options: ENTITIES.map((e) => ({ value: e, label: titleCase(e) })) },
  list: ({ filter, limit, offset }) =>
    unwrap(
      api.GET('/api/v1/audit-logs', { params: { query: { entity_type: filter, limit, offset } } }),
    ),
  columns: [
    {
      header: 'When',
      cell: (e) => formatDateTime(e.created_at),
      className: 'whitespace-nowrap text-muted tabular',
    },
    { header: 'Who', cell: (e) => e.actor?.full_name ?? 'Removed user' },
    {
      header: 'What',
      cell: (e) => <span className="font-medium">{titleCase(e.action.replace('.', ' '))}</span>,
    },
    {
      header: 'Details',
      cell: (e) => (
        <ul className="grid gap-0.5 text-xs text-muted">
          {Object.entries(e.changes)
            .slice(0, 4)
            .map(([field, value]) => (
              <li key={field}>
                <span className="text-text">{titleCase(field)}</span>: {describeChange(value)}
              </li>
            ))}
        </ul>
      ),
    },
  ],
}

export const AuditPage = () => <ResourcePage config={audit} />
