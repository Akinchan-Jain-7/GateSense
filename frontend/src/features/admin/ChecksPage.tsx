import { Check } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { formatDateTime } from '@/lib/format'
import { useAction } from '@/lib/queries'

import { ResourcePage, type ResourceConfig } from './ResourcePage'

const KIND: Record<Schemas['ReconciliationKind'], string> = {
  exit_without_entry: 'Exit without an entry',
  entry_never_closed: 'Entry never closed',
  visit_not_closed: 'Visit never closed',
}

function ResolveButton({ flag }: { flag: Schemas['ReconciliationFlagRead'] }) {
  const resolve = useAction(
    () =>
      unwrap(
        api.POST('/api/v1/reconciliation/{flag_id}/resolve', {
          params: { path: { flag_id: flag.id } },
        }),
      ),
    { invalidate: [['checks']], success: 'Marked as checked' },
  )
  if (flag.resolved_at) return <Badge tone="ok">Checked</Badge>
  return (
    <Button
      variant="secondary"
      size="sm"
      disabled={resolve.isPending}
      onClick={() => {
        resolve.mutate(undefined)
      }}
    >
      <Check /> Mark checked
    </Button>
  )
}

const checks: ResourceConfig<Schemas['ReconciliationFlagRead']> = {
  key: 'checks',
  title: 'Gate checks',
  singular: 'Check',
  description:
    'Every night the gate records are compared. Anything that doesn’t add up lands here.',
  filter: {
    label: 'Show',
    options: [
      { value: 'open', label: 'Needs a look' },
      { value: 'resolved', label: 'Checked' },
    ],
  },
  list: ({ filter, limit, offset }) =>
    unwrap(
      api.GET('/api/v1/reconciliation', {
        params: { query: { resolved: filter ? filter === 'resolved' : undefined, limit, offset } },
      }),
    ),
  columns: [
    {
      header: 'Found',
      cell: (f) => formatDateTime(f.created_at),
      className: 'whitespace-nowrap text-muted tabular',
    },
    { header: 'Problem', cell: (f) => <span className="font-medium">{KIND[f.kind]}</span> },
    { header: 'Details', cell: (f) => <span className="text-muted">{f.details}</span> },
  ],
  rowActions: (f) => <ResolveButton flag={f} />,
}

export const ChecksPage = () => <ResourcePage config={checks} />
