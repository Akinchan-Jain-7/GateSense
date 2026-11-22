import { Copy, Plus, Ticket } from 'lucide-react'
import { useState, type SubmitEvent } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Plate } from '@/components/ui/plate'
import { SkeletonRows } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/ui/states'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { cleanPlateInput } from '@/lib/plates'
import { useAction, type GuestPass } from '@/lib/queries'
import { useQuery } from '@tanstack/react-query'

type Window = 'hours' | 'today' | 'tomorrow' | 'custom'

const WINDOWS: { id: Window; label: string }[] = [
  { id: 'hours', label: 'Next 4 hours' },
  { id: 'today', label: 'Rest of today' },
  { id: 'tomorrow', label: 'Tomorrow' },
  { id: 'custom', label: 'Pick times' },
]

/** Start and end of a validity window, computed from the device clock. */
export function windowRange(
  choice: Exclude<Window, 'custom'>,
  now: Date = new Date(),
): [Date, Date] {
  const endOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59)
  if (choice === 'hours') return [now, new Date(now.getTime() + 4 * 3_600_000)]
  if (choice === 'today') return [now, endOfDay(now)]
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  return [tomorrow, endOfDay(tomorrow)]
}

function toLocalInput(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${date.getFullYear().toString()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function Segmented<T extends string>({
  name,
  options,
  value,
  onChange,
  legend,
}: {
  name: string
  options: { id: T; label: string }[]
  value: T
  onChange: (value: T) => void
  legend: string
}) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium">{legend}</legend>
      <div
        className={cn(
          'grid gap-1 rounded-lg border border-border p-1',
          options.length === 2 ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-4',
        )}
      >
        {options.map((option) => (
          <label
            key={option.id}
            className="flex h-10 cursor-pointer items-center justify-center rounded-md px-2 text-center text-sm font-medium text-muted has-[:checked]:bg-accent-soft has-[:checked]:text-accent has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent"
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              checked={value === option.id}
              onChange={() => {
                onChange(option.id)
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function NewPassForm({ onCreated }: { onCreated: (result: Schemas['GuestPassCreated']) => void }) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [method, setMethod] = useState<'plate' | 'code'>('plate')
  const [plate, setPlate] = useState('')
  const [window, setWindow] = useState<Window>('hours')
  const [from, setFrom] = useState(() => toLocalInput(new Date()))
  const [until, setUntil] = useState(() => toLocalInput(new Date(Date.now() + 4 * 3_600_000)))
  const [uses, setUses] = useState('1')

  const create = useAction(
    (body: Schemas['GuestPassCreate']) => unwrap(api.POST('/api/v1/guest-passes', { body })),
    { invalidate: [['guest-passes']], onSuccess: onCreated },
  )

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    const [start, end] =
      window === 'custom' ? [new Date(from), new Date(until)] : windowRange(window)
    create.mutate({
      guest_name: name.trim(),
      guest_phone: phone.trim() || null,
      plate: method === 'plate' ? cleanPlateInput(plate) : null,
      with_code: method === 'code',
      valid_from: start.toISOString(),
      valid_until: end.toISOString(),
      max_uses: Number(uses),
      category: 'guest',
    })
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <Field id="guest-name" label="Guest’s name">
        <Input
          id="guest-name"
          required
          minLength={2}
          autoFocus
          value={name}
          onChange={(e) => {
            setName(e.target.value)
          }}
        />
      </Field>
      <Segmented
        legend="How will the guard recognise them?"
        name="method"
        value={method}
        onChange={setMethod}
        options={[
          { id: 'plate', label: 'Car number' },
          { id: 'code', label: 'A code they show' },
        ]}
      />
      {method === 'plate' ? (
        <Field
          id="guest-plate"
          label="Car number"
          hint="The gate camera lets this car in automatically."
        >
          <Input
            id="guest-plate"
            required
            className="uppercase"
            placeholder="DL 3C AB 1234"
            value={plate}
            onChange={(e) => {
              setPlate(e.target.value)
            }}
          />
        </Field>
      ) : (
        <p className="rounded-lg bg-surface-2 p-3 text-sm text-muted">
          You’ll get a code to send them. They show it to the guard, who types it in.
        </p>
      )}
      <Segmented
        legend="When"
        name="window"
        value={window}
        onChange={setWindow}
        options={WINDOWS}
      />
      {window === 'custom' ? (
        <div className="grid grid-cols-2 gap-3">
          <Field id="pass-from" label="From">
            <Input
              id="pass-from"
              type="datetime-local"
              required
              value={from}
              onChange={(e) => {
                setFrom(e.target.value)
              }}
            />
          </Field>
          <Field id="pass-until" label="Until">
            <Input
              id="pass-until"
              type="datetime-local"
              required
              value={until}
              onChange={(e) => {
                setUntil(e.target.value)
              }}
            />
          </Field>
        </div>
      ) : null}
      <div className="grid grid-cols-2 gap-3">
        <Field id="guest-phone" label="Their mobile (optional)">
          <Input
            id="guest-phone"
            type="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => {
              setPhone(e.target.value)
            }}
          />
        </Field>
        <Field id="pass-uses" label="Entries allowed">
          <Input
            id="pass-uses"
            type="number"
            min={1}
            max={50}
            required
            value={uses}
            onChange={(e) => {
              setUses(e.target.value)
            }}
          />
        </Field>
      </div>
      <Button type="submit" size="lg" disabled={create.isPending}>
        Create guest pass
      </Button>
    </form>
  )
}

function CreatedNotice({
  result,
  onClose,
}: {
  result: Schemas['GuestPassCreated']
  onClose: () => void
}) {
  const pass = result.guest_pass
  const message = result.code
    ? `Hi ${pass.guest_name}, show this code to the guard at the gate: ${result.code}`
    : null
  return (
    <div className="grid gap-4">
      {result.code ? (
        <>
          <p className="text-sm text-muted">
            Send this code to {pass.guest_name}. It’s shown only once.
          </p>
          <p className="rounded-xl border border-border bg-surface-2 py-5 text-center font-plate text-3xl font-semibold tracking-[0.3em]">
            {result.code}
          </p>
          <Button
            variant="secondary"
            onClick={() => {
              void navigator.clipboard
                .writeText(message ?? result.code ?? '')
                .then(() => toast.success('Copied'))
            }}
          >
            <Copy /> Copy a message with the code
          </Button>
        </>
      ) : (
        <p className="text-sm text-muted">
          {pass.plate_normalized ? (
            <Plate plate={pass.plate_normalized} size="sm" className="mr-1 align-middle" />
          ) : null}{' '}
          will be let in automatically until {formatDateTime(pass.valid_until)}.
        </p>
      )}
      <Button onClick={onClose}>Done</Button>
    </div>
  )
}

function PassCard({ pass }: { pass: GuestPass }) {
  const revoke = useAction(
    () =>
      unwrap(
        api.POST('/api/v1/guest-passes/{pass_id}/revoke', {
          params: { path: { pass_id: pass.id } },
        }),
      ),
    { invalidate: [['guest-passes']], success: 'Guest pass cancelled' },
  )
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="grid gap-1">
          <p className="font-semibold">{pass.guest_name}</p>
          <p className="text-xs text-muted">
            {formatDateTime(pass.valid_from)} to {formatDateTime(pass.valid_until)}
          </p>
        </div>
        <Badge tone="ok" className="tabular">
          {pass.use_count.toString()} of {pass.max_uses.toString()} used
        </Badge>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        {pass.plate_normalized ? (
          <Plate plate={pass.plate_normalized} size="sm" />
        ) : (
          <Badge>Code pass</Badge>
        )}
        <ConfirmDialog
          trigger={
            <Button variant="ghost" size="sm">
              Cancel pass
            </Button>
          }
          title="Cancel this guest pass?"
          description={`${pass.guest_name} will have to wait for your approval at the gate instead.`}
          confirmLabel="Cancel pass"
          onConfirm={() => revoke.mutateAsync(undefined)}
        />
      </div>
    </Card>
  )
}

export function PassesPage() {
  const [open, setOpen] = useState(false)
  const [created, setCreated] = useState<Schemas['GuestPassCreated'] | null>(null)
  const passes = useQuery({
    queryKey: ['guest-passes', 'active'],
    queryFn: () =>
      unwrap(api.GET('/api/v1/guest-passes', { params: { query: { active: true, limit: 50 } } })),
  })

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Guest passes</h1>
        <Button
          onClick={() => {
            setCreated(null)
            setOpen(true)
          }}
        >
          <Plus /> New pass
        </Button>
      </div>
      {passes.isLoading ? <SkeletonRows rows={2} /> : null}
      {passes.isError ? (
        <ErrorState error={passes.error} onRetry={() => void passes.refetch()} />
      ) : null}
      {passes.data?.items.length === 0 ? (
        <EmptyState
          icon={Ticket}
          title="No guest passes yet"
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setOpen(true)
              }}
            >
              Create one
            </Button>
          }
        >
          Expecting someone? Give them a pass and they won’t have to wait at the gate.
        </EmptyState>
      ) : null}
      <div className="grid gap-3">
        {passes.data?.items.map((pass) => (
          <PassCard key={pass.id} pass={pass} />
        ))}
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          title={created ? 'Guest pass ready' : 'New guest pass'}
          description={created ? undefined : 'They’ll be let in without waiting for your approval.'}
        >
          {created ? (
            <CreatedNotice
              result={created}
              onClose={() => {
                setOpen(false)
              }}
            />
          ) : (
            <NewPassForm onCreated={setCreated} />
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
