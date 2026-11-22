import { useQuery } from '@tanstack/react-query'
import { Copy, KeyRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Plate } from '@/components/ui/plate'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { formatAgo, maskPhone, titleCase } from '@/lib/format'
import { cleanPlateInput } from '@/lib/plates'
import { useAction } from '@/lib/queries'

import {
  clean,
  ResourcePage,
  type FieldDef,
  type ResourceConfig,
  type Values,
} from './ResourcePage'

/** Form values as an API body. The server validates every field (and says what's wrong). */
function body<T>(values: Values, fields: FieldDef[]): NonNullable<T> {
  return clean(values, fields) as unknown as NonNullable<T>
}

function Active({ on }: { on: boolean }) {
  return on ? <Badge tone="ok">Active</Badge> : <Badge>Inactive</Badge>
}

const yesNo = (v: boolean) => String(v)

// --- Flats --------------------------------------------------------------------------

const flatCreate: FieldDef[] = [
  { name: 'block', label: 'Block', required: true, placeholder: 'B' },
  { name: 'number', label: 'Flat number', required: true, placeholder: '402' },
  { name: 'floor', label: 'Floor', type: 'number' },
  { name: 'parking_slots', label: 'Parking slots', type: 'number' },
]
const flats: ResourceConfig<Schemas['FlatRead']> = {
  key: 'flats',
  title: 'Flats',
  singular: 'Flat',
  description: 'Every flat in the society. Residents and vehicles belong to a flat.',
  search: 'Search flats, e.g. B-402',
  list: ({ q, limit, offset }) =>
    unwrap(api.GET('/api/v1/flats', { params: { query: { q, limit, offset } } })),
  columns: [
    { header: 'Flat', cell: (f) => <span className="font-medium tabular">{f.label}</span> },
    { header: 'Floor', cell: (f) => f.floor ?? '—', className: 'tabular' },
    { header: 'Parking slots', cell: (f) => f.parking_slots, className: 'tabular' },
  ],
  create: {
    fields: flatCreate,
    submit: (v) => unwrap(api.POST('/api/v1/flats', { body: body(v, flatCreate) })),
  },
  edit: {
    fields: flatCreate.slice(2),
    initial: (f) => ({ floor: String(f.floor ?? ''), parking_slots: String(f.parking_slots) }),
    submit: (f, v) =>
      unwrap(
        api.PATCH('/api/v1/flats/{flat_id}', {
          params: { path: { flat_id: f.id } },
          body: body(v, flatCreate.slice(2)),
        }),
      ),
  },
  remove: {
    describe: (f) =>
      `${f.label} will be removed. This only works when it has no residents or vehicles.`,
    submit: (f) =>
      unwrap(api.DELETE('/api/v1/flats/{flat_id}', { params: { path: { flat_id: f.id } } })),
  },
}
export const FlatsPage = () => <ResourcePage config={flats} />

// --- Residents ----------------------------------------------------------------------

const RESIDENT_TYPES = [
  { value: 'owner', label: 'Owner' },
  { value: 'tenant', label: 'Tenant' },
  { value: 'family', label: 'Family member' },
]
const residentCreate: FieldDef[] = [
  { name: 'full_name', label: 'Full name', required: true },
  { name: 'email', label: 'Email', type: 'email', required: true },
  { name: 'phone', label: 'Mobile number', type: 'tel' },
  { name: 'flat_id', label: 'Flat', type: 'flat', required: true },
  {
    name: 'resident_type',
    label: 'Lives there as',
    type: 'select',
    options: RESIDENT_TYPES,
    required: true,
  },
  {
    name: 'password',
    label: 'First password',
    type: 'password',
    required: true,
    hint: 'At least 8 characters. Ask them to change it.',
  },
  { name: 'is_primary_contact', label: 'Primary contact for the flat', type: 'checkbox' },
]
const residentEdit: FieldDef[] = [
  { name: 'full_name', label: 'Full name', required: true },
  { name: 'phone', label: 'Mobile number', type: 'tel' },
  {
    name: 'resident_type',
    label: 'Lives there as',
    type: 'select',
    options: RESIDENT_TYPES,
    required: true,
  },
  { name: 'is_primary_contact', label: 'Primary contact for the flat', type: 'checkbox' },
  { name: 'is_active', label: 'Account active (can sign in)', type: 'checkbox' },
]
const residents: ResourceConfig<Schemas['ResidentRead']> = {
  key: 'residents',
  title: 'Residents',
  singular: 'Resident',
  description: 'People who can approve visitors and create guest passes for their flat.',
  search: 'Search by name or email',
  filter: { label: 'Type', options: RESIDENT_TYPES },
  list: ({ q, filter, limit, offset }) =>
    unwrap(
      api.GET('/api/v1/residents', {
        params: {
          query: { q, limit, offset, resident_type: filter as Schemas['ResidentType'] | undefined },
        },
      }),
    ),
  columns: [
    {
      header: 'Name',
      cell: (r) => (
        <div>
          <p className="font-medium">{r.user.full_name}</p>
          <p className="text-xs text-muted">{r.user.email}</p>
        </div>
      ),
    },
    { header: 'Flat', cell: (r) => <span className="tabular">{r.flat.label}</span> },
    {
      header: 'Type',
      cell: (r) =>
        r.is_primary_contact
          ? `${titleCase(r.resident_type)}, primary`
          : titleCase(r.resident_type),
    },
    {
      header: 'Mobile',
      cell: (r) => <span className="text-muted tabular">{maskPhone(r.user.phone)}</span>,
    },
    { header: 'Status', cell: (r) => <Active on={r.user.is_active} /> },
  ],
  create: {
    fields: residentCreate,
    submit: (v) => unwrap(api.POST('/api/v1/residents', { body: body(v, residentCreate) })),
  },
  edit: {
    fields: residentEdit,
    initial: (r) => ({
      full_name: r.user.full_name,
      phone: r.user.phone ?? '',
      resident_type: r.resident_type,
      is_primary_contact: yesNo(r.is_primary_contact),
      is_active: yesNo(r.user.is_active),
    }),
    submit: (r, v) =>
      unwrap(
        api.PATCH('/api/v1/residents/{resident_id}', {
          params: { path: { resident_id: r.id } },
          body: body(v, residentEdit),
        }),
      ),
  },
  remove: {
    describe: (r) =>
      `${r.user.full_name} will lose access and stop getting approval requests for ${r.flat.label}.`,
    submit: (r) =>
      unwrap(
        api.DELETE('/api/v1/residents/{resident_id}', { params: { path: { resident_id: r.id } } }),
      ),
  },
}
export const ResidentsPage = () => <ResourcePage config={residents} />

// --- Vehicles -----------------------------------------------------------------------

const VEHICLE_TYPES = [
  { value: 'car', label: 'Car' },
  { value: 'two_wheeler', label: 'Two-wheeler' },
]
const vehicleCreate: FieldDef[] = [
  { name: 'plate', label: 'Number plate', required: true, placeholder: 'UP16 AB 1234' },
  { name: 'flat_id', label: 'Flat', type: 'flat', required: true },
  { name: 'vehicle_type', label: 'Type', type: 'select', options: VEHICLE_TYPES, required: true },
  { name: 'make_model', label: 'Make and model', placeholder: 'Maruti Swift' },
  { name: 'colour', label: 'Colour' },
]
const vehicleEdit: FieldDef[] = [
  { name: 'make_model', label: 'Make and model' },
  { name: 'colour', label: 'Colour' },
  { name: 'is_active', label: 'Let in automatically', type: 'checkbox' },
]
const vehicles: ResourceConfig<Schemas['VehicleRead']> = {
  key: 'vehicles',
  title: 'Vehicles',
  singular: 'Vehicle',
  description: 'Residents’ vehicles are let in and out automatically when the camera reads them.',
  search: 'Search by plate',
  filter: { label: 'Type', options: VEHICLE_TYPES },
  list: ({ q, filter, limit, offset }) =>
    unwrap(
      api.GET('/api/v1/vehicles', {
        params: {
          query: {
            q: q ? cleanPlateInput(q) : undefined,
            limit,
            offset,
            vehicle_type: filter as Schemas['VehicleType'] | undefined,
          },
        },
      }),
    ),
  columns: [
    { header: 'Plate', cell: (v) => <Plate plate={v.plate_normalized} size="sm" /> },
    { header: 'Flat', cell: (v) => <span className="tabular">{v.flat.label}</span> },
    {
      header: 'Vehicle',
      cell: (v) => [titleCase(v.vehicle_type), v.make_model, v.colour].filter(Boolean).join(', '),
    },
    { header: 'Status', cell: (v) => <Active on={v.is_active} /> },
  ],
  create: {
    fields: vehicleCreate,
    submit: (v) => unwrap(api.POST('/api/v1/vehicles', { body: body(v, vehicleCreate) })),
  },
  edit: {
    fields: vehicleEdit,
    initial: (v) => ({
      make_model: v.make_model ?? '',
      colour: v.colour ?? '',
      is_active: yesNo(v.is_active),
    }),
    submit: (v, values) =>
      unwrap(
        api.PATCH('/api/v1/vehicles/{vehicle_id}', {
          params: { path: { vehicle_id: v.id } },
          body: body(values, vehicleEdit),
        }),
      ),
  },
  remove: {
    describe: (v) => `${v.plate_normalized} will be treated as an unknown vehicle at the gate.`,
    submit: (v) =>
      unwrap(
        api.DELETE('/api/v1/vehicles/{vehicle_id}', { params: { path: { vehicle_id: v.id } } }),
      ),
  },
}
export const VehiclesPage = () => <ResourcePage config={vehicles} />

// --- Guards -------------------------------------------------------------------------

const guardCreate: FieldDef[] = [
  { name: 'full_name', label: 'Full name', required: true },
  { name: 'email', label: 'Email', type: 'email', required: true },
  { name: 'phone', label: 'Mobile number', type: 'tel' },
  { name: 'password', label: 'First password', type: 'password', required: true },
]
const guardEdit: FieldDef[] = [
  { name: 'full_name', label: 'Full name', required: true },
  { name: 'phone', label: 'Mobile number', type: 'tel' },
  { name: 'is_active', label: 'Can sign in', type: 'checkbox' },
]
const guards: ResourceConfig<Schemas['GuardRead']> = {
  key: 'guards',
  title: 'Guards',
  singular: 'Guard',
  description: 'Guards sign in to the gate console.',
  search: 'Search by name or email',
  list: ({ q, limit, offset }) =>
    unwrap(api.GET('/api/v1/guards', { params: { query: { q, limit, offset } } })),
  columns: [
    {
      header: 'Name',
      cell: (g) => (
        <div>
          <p className="font-medium">{g.full_name}</p>
          <p className="text-xs text-muted">{g.email}</p>
        </div>
      ),
    },
    {
      header: 'Mobile',
      cell: (g) => <span className="text-muted tabular">{maskPhone(g.phone)}</span>,
    },
    {
      header: 'Last signed in',
      cell: (g) => (g.last_login_at ? formatAgo(g.last_login_at) : 'Never'),
      className: 'text-muted',
    },
    { header: 'Status', cell: (g) => <Active on={g.is_active} /> },
  ],
  create: {
    fields: guardCreate,
    submit: (v) => unwrap(api.POST('/api/v1/guards', { body: body(v, guardCreate) })),
  },
  edit: {
    fields: guardEdit,
    initial: (g) => ({
      full_name: g.full_name,
      phone: g.phone ?? '',
      is_active: yesNo(g.is_active),
    }),
    submit: (g, v) =>
      unwrap(
        api.PATCH('/api/v1/guards/{guard_id}', {
          params: { path: { guard_id: g.id } },
          body: body(v, guardEdit),
        }),
      ),
  },
  remove: {
    describe: (g) => `${g.full_name} will no longer be able to sign in.`,
    submit: (g) =>
      unwrap(api.DELETE('/api/v1/guards/{guard_id}', { params: { path: { guard_id: g.id } } })),
  },
}
export const GuardsPage = () => <ResourcePage config={guards} />

// --- Watchlist ----------------------------------------------------------------------

const watchCreate: FieldDef[] = [
  { name: 'plate', label: 'Number plate', required: true },
  { name: 'reason', label: 'Reason (the guard sees this)', type: 'textarea', required: true },
]
const watchEdit: FieldDef[] = [
  { name: 'reason', label: 'Reason (the guard sees this)', type: 'textarea', required: true },
  { name: 'is_active', label: 'Alert the guard when this plate is read', type: 'checkbox' },
]
const watchlist: ResourceConfig<Schemas['WatchlistRead']> = {
  key: 'watchlist',
  title: 'Watchlist',
  singular: 'Watchlist entry',
  description: 'When the camera reads one of these plates, the guard gets a red alert.',
  search: 'Search by plate',
  list: ({ q, limit, offset }) =>
    unwrap(api.GET('/api/v1/watchlist', { params: { query: { q, limit, offset } } })),
  columns: [
    { header: 'Plate', cell: (w) => <Plate plate={w.plate_normalized} size="sm" /> },
    { header: 'Reason', cell: (w) => <span className="line-clamp-2 max-w-md">{w.reason}</span> },
    { header: 'Added', cell: (w) => formatAgo(w.created_at), className: 'text-muted' },
    { header: 'Status', cell: (w) => <Active on={w.is_active} /> },
  ],
  create: {
    fields: watchCreate,
    submit: (v) => unwrap(api.POST('/api/v1/watchlist', { body: body(v, watchCreate) })),
  },
  edit: {
    fields: watchEdit,
    initial: (w) => ({ reason: w.reason, is_active: yesNo(w.is_active) }),
    submit: (w, v) =>
      unwrap(
        api.PATCH('/api/v1/watchlist/{entry_id}', {
          params: { path: { entry_id: w.id } },
          body: body(v, watchEdit),
        }),
      ),
  },
  remove: {
    describe: (w) => `${w.plate_normalized} will no longer raise an alert.`,
    submit: (w) =>
      unwrap(api.DELETE('/api/v1/watchlist/{entry_id}', { params: { path: { entry_id: w.id } } })),
  },
}
export const WatchlistPage = () => <ResourcePage config={watchlist} />

// --- Gates and cameras --------------------------------------------------------------

const gateFields: FieldDef[] = [
  { name: 'name', label: 'Name', required: true, placeholder: 'Main Gate' },
  { name: 'location', label: 'Where it is' },
]
const gates: ResourceConfig<Schemas['GateRead']> = {
  key: 'gates',
  title: 'Gates',
  singular: 'Gate',
  description: 'Each gate has an entry camera and an exit camera.',
  list: ({ limit, offset }) =>
    unwrap(api.GET('/api/v1/gates', { params: { query: { limit, offset } } })),
  columns: [
    { header: 'Gate', cell: (g) => <span className="font-medium">{g.name}</span> },
    { header: 'Location', cell: (g) => g.location ?? '—', className: 'text-muted' },
    { header: 'Status', cell: (g) => <Active on={g.is_active} /> },
  ],
  create: {
    fields: gateFields,
    submit: (v) => unwrap(api.POST('/api/v1/gates', { body: body(v, gateFields) })),
  },
  edit: {
    fields: [...gateFields, { name: 'is_active', label: 'In use', type: 'checkbox' }],
    initial: (g) => ({ name: g.name, location: g.location ?? '', is_active: yesNo(g.is_active) }),
    submit: (g, v) =>
      unwrap(
        api.PATCH('/api/v1/gates/{gate_id}', {
          params: { path: { gate_id: g.id } },
          body: body(v, [...gateFields, { name: 'is_active', label: '', type: 'checkbox' }]),
        }),
      ),
  },
}

function KeyDialog({
  device,
  onClose,
}: {
  device: Schemas['DeviceWithKey'] | null
  onClose: () => void
}) {
  return (
    <Dialog
      open={device !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        title="Camera key"
        description="Copy it into the camera’s settings now. It is shown only once; if it’s lost, rotate the key."
      >
        <code className="block rounded-lg border border-border bg-surface-2 p-3 text-sm break-all">
          {device?.api_key}
        </code>
        <div className="mt-4 flex justify-end gap-2">
          <Button
            variant="secondary"
            onClick={() => {
              void navigator.clipboard
                .writeText(device?.api_key ?? '')
                .then(() => toast.success('Key copied'))
            }}
          >
            <Copy /> Copy key
          </Button>
          <Button onClick={onClose}>Done</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function GatesPage() {
  const [key, setKey] = useState<Schemas['DeviceWithKey'] | null>(null)
  const allGates = useQuery({
    queryKey: ['gates', 'all'],
    queryFn: () => unwrap(api.GET('/api/v1/gates', { params: { query: { limit: 100 } } })),
  })
  const gateName = useMemo(
    () => new Map((allGates.data?.items ?? []).map((g) => [g.id, g.name])),
    [allGates.data],
  )
  const rotate = useAction(
    (id: string) =>
      unwrap(
        api.POST('/api/v1/devices/{device_id}/rotate-key', { params: { path: { device_id: id } } }),
      ),
    { invalidate: [['devices']], onSuccess: setKey },
  )

  const deviceFields: FieldDef[] = [
    { name: 'name', label: 'Name', required: true, placeholder: 'Main Gate - entry camera' },
    {
      name: 'gate_id',
      label: 'Gate',
      type: 'select',
      required: true,
      options: (allGates.data?.items ?? []).map((g) => ({ value: g.id, label: g.name })),
    },
    {
      name: 'direction',
      label: 'Lane',
      type: 'select',
      required: true,
      options: [
        { value: 'entry', label: 'Entry' },
        { value: 'exit', label: 'Exit' },
      ],
    },
  ]
  const devices: ResourceConfig<Schemas['DeviceRead']> = {
    key: 'devices',
    title: 'Cameras',
    singular: 'Camera',
    description: 'Each camera signs its plate reads with its own key.',
    list: ({ limit, offset }) =>
      unwrap(api.GET('/api/v1/devices', { params: { query: { limit, offset } } })),
    columns: [
      { header: 'Camera', cell: (d) => <span className="font-medium">{d.name}</span> },
      { header: 'Gate', cell: (d) => gateName.get(d.gate_id) ?? '—' },
      { header: 'Lane', cell: (d) => titleCase(d.direction) },
      {
        header: 'Key',
        cell: (d) => <code className="text-xs text-muted">{d.api_key_prefix}…</code>,
      },
      {
        header: 'Last seen',
        cell: (d) => (d.last_seen_at ? formatAgo(d.last_seen_at) : 'Never'),
        className: 'text-muted',
      },
      { header: 'Status', cell: (d) => <Active on={d.is_active} /> },
    ],
    create: {
      fields: deviceFields,
      submit: (v) => unwrap(api.POST('/api/v1/devices', { body: body(v, deviceFields) })),
      done: (result) => {
        setKey(result as Schemas['DeviceWithKey'])
      },
    },
    rowActions: (d) => (
      <ConfirmDialog
        trigger={
          <Button variant="ghost" size="icon" className="size-8" aria-label="Rotate camera key">
            <KeyRound />
          </Button>
        }
        title="Rotate this camera’s key?"
        description={`${d.name} stops working until its new key is entered in the camera.`}
        confirmLabel="Rotate key"
        onConfirm={() => rotate.mutateAsync(d.id)}
      />
    ),
    remove: {
      describe: (d) => `${d.name} will no longer be able to send plate reads.`,
      submit: (d) =>
        unwrap(
          api.DELETE('/api/v1/devices/{device_id}', { params: { path: { device_id: d.id } } }),
        ),
    },
  }

  return (
    <div className="grid gap-10">
      <ResourcePage config={gates} />
      <ResourcePage config={devices} />
      <KeyDialog
        device={key}
        onClose={() => {
          setKey(null)
        }}
      />
    </div>
  )
}
