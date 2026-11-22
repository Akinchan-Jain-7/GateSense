import { useQueryClient } from '@tanstack/react-query'
import { RotateCcw } from 'lucide-react'
import { useState, type SubmitEvent } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/ui/states'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { useAuth } from '@/lib/auth'
import { useAction, useDemoInfo, useVisitSettings } from '@/lib/queries'

import { PageHeader } from './PageHeader'

type Settings = Schemas['VisitSettingsRead']
type Key = keyof Settings

const GROUPS: {
  title: string
  description: string
  fields: {
    key: Key
    label: string
    unit: string
    min: number
    max: number
    step?: number
    hint?: string
  }[]
}[] = [
  {
    title: 'Visit time limits',
    description:
      'How long each kind of visitor may stay. Overstays start the reminder emails, then a call from the guard.',
    fields: [
      { key: 'guest_minutes', label: 'Guests', unit: 'minutes', min: 5, max: 1440 },
      { key: 'delivery_minutes', label: 'Deliveries', unit: 'minutes', min: 5, max: 240 },
      { key: 'cab_minutes', label: 'Cabs', unit: 'minutes', min: 2, max: 120 },
      {
        key: 'service_minutes',
        label: 'Service visits',
        unit: 'minutes',
        min: 10,
        max: 1440,
        hint: 'Used when a resident doesn’t set a time.',
      },
    ],
  },
  {
    title: 'At the gate',
    description: 'How the gate handles approvals, uncertain plate reads and parking.',
    fields: [
      {
        key: 'approval_timeout_seconds',
        label: 'Time residents get to answer',
        unit: 'seconds',
        min: 30,
        max: 1800,
        hint: 'After this the guard decides.',
      },
      {
        key: 'plate_confidence_threshold',
        label: 'Plate reads below this go to the guard',
        unit: '0.30 – 0.99',
        min: 0.3,
        max: 0.99,
        step: 0.01,
        hint: 'Higher means more manual checks but fewer wrong matches.',
      },
      {
        key: 'visitor_parking_slots',
        label: 'Visitor parking spaces',
        unit: 'spaces',
        min: 0,
        max: 500,
      },
    ],
  },
  {
    title: 'Privacy',
    description:
      'Visitors’ names, phone numbers, emails and plate snapshots are deleted after this.',
    fields: [
      {
        key: 'visitor_retention_days',
        label: 'Keep visitor data for',
        unit: 'days',
        min: 7,
        max: 3650,
      },
    ],
  },
]

function SettingsForm({ settings }: { settings: Settings }) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(settings).map(([k, v]) => [k, String(v)])),
  )

  const save = useAction(
    (body: Schemas['VisitSettingsUpdate']) =>
      unwrap(api.PATCH('/api/v1/settings/visits', { body })),
    {
      invalidate: [['settings'], ['audit'], ['analytics']],
      success: 'Settings saved. New visits use them from now on.',
    },
  )

  const changed = Object.entries(values).filter(([k, v]) => String(settings[k as Key]) !== v)

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    save.mutate(Object.fromEntries(changed.map(([k, v]) => [k, Number(v)])))
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      {GROUPS.map((group) => (
        <Card key={group.title}>
          <CardHeader className="block">
            <CardTitle>{group.title}</CardTitle>
            <p className="mt-1 text-sm text-muted">{group.description}</p>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            {group.fields.map((f) => (
              <Field
                key={f.key}
                id={f.key}
                label={f.label}
                hint={f.hint ? `${f.unit}. ${f.hint}` : f.unit}
              >
                <Input
                  id={f.key}
                  type="number"
                  required
                  min={f.min}
                  max={f.max}
                  step={f.step ?? 1}
                  className="tabular"
                  value={values[f.key] ?? ''}
                  onChange={(e) => {
                    setValues((current) => ({ ...current, [f.key]: e.target.value }))
                  }}
                />
              </Field>
            ))}
          </CardContent>
        </Card>
      ))}
      <div className="sticky bottom-4 flex items-center justify-end gap-3">
        {changed.length > 0 ? (
          <p className="text-sm text-muted">
            {changed.length.toString()} unsaved {changed.length === 1 ? 'change' : 'changes'}
          </p>
        ) : null}
        <Button type="submit" disabled={changed.length === 0 || save.isPending}>
          Save settings
        </Button>
      </div>
    </form>
  )
}

function DemoCard() {
  const demo = useDemoInfo()
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const client = useQueryClient()
  if (!demo.data?.enabled) return null
  const admin = demo.data.accounts.find((a) => a.role === 'admin')

  async function reset() {
    try {
      await unwrap(api.POST('/api/v1/demo/reset'))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Reset failed')
      throw error
    }
    // Every account was recreated, so sign in again as the demo admin.
    client.clear()
    if (admin && demo.data?.password) await signIn(admin.email, demo.data.password)
    toast.success('Demo data reset')
    void navigate('/admin')
  }

  return (
    <Card className="mt-8">
      <CardHeader className="block">
        <CardTitle>Demo data</CardTitle>
        <p className="mt-1 text-sm text-muted">
          Put the demo society back to a fresh state: two weeks of made-up history and a few things
          happening at the gate right now.
        </p>
      </CardHeader>
      <CardContent>
        <ConfirmDialog
          trigger={
            <Button variant="danger-outline">
              <RotateCcw /> Reset demo
            </Button>
          }
          title="Reset the demo?"
          description="All demo data is replaced and everyone using the demo is signed out."
          confirmLabel="Reset demo"
          onConfirm={reset}
        />
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const settings = useVisitSettings()
  return (
    <div className="max-w-3xl">
      <PageHeader title="Settings" description="Changes are recorded in the audit log." />
      {settings.isLoading ? <Skeleton className="h-96 rounded-xl" /> : null}
      {settings.isError ? (
        <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
      ) : null}
      {/* Remount when the saved settings change, so the form shows what's stored. */}
      {settings.data ? (
        <SettingsForm key={JSON.stringify(settings.data)} settings={settings.data} />
      ) : null}
      <DemoCard />
    </div>
  )
}
