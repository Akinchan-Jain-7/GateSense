/**
 * One page layout for every admin table (flats, residents, vehicles, ...): search, an
 * optional filter, pagination, and create / edit / delete through a dialog. Each
 * resource passes typed API functions, so the generated API types still apply.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Inbox, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { useEffect, useState, type SubmitEvent, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Select, Textarea } from '@/components/ui/input'
import { Pagination } from '@/components/ui/pagination'
import { SkeletonRows } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/ui/states'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import { useAction, useAllFlats } from '@/lib/queries'

import { PageHeader } from './PageHeader'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Column<T> {
  header: string
  cell: (row: T) => ReactNode
  className?: string
}

export interface FieldDef {
  name: string
  label: string
  type?:
    'text' | 'email' | 'tel' | 'password' | 'number' | 'select' | 'textarea' | 'checkbox' | 'flat'
  options?: { value: string; label: string }[]
  required?: boolean
  hint?: string
  placeholder?: string
}

export type Values = Record<string, string>

export interface ListParams {
  q?: string
  filter?: string
  limit: number
  offset: number
}

export interface ResourceConfig<T extends { id: string }> {
  key: string
  title: string
  description: string
  singular: string
  list: (params: ListParams) => Promise<Page<T>>
  columns: Column<T>[]
  search?: string
  filter?: { label: string; options: { value: string; label: string }[] }
  create?: {
    fields: FieldDef[]
    submit: (values: Values) => Promise<unknown>
    done?: (result: unknown) => void
  }
  edit?: {
    fields: FieldDef[]
    initial: (row: T) => Values
    submit: (row: T, values: Values) => Promise<unknown>
  }
  remove?: { describe: (row: T) => string; submit: (row: T) => Promise<unknown> }
  rowActions?: (row: T) => ReactNode
}

const PAGE = 20

/** Empty strings mean "not given": turn them into null, numbers into numbers. */
export function clean(
  values: Values,
  fields: FieldDef[],
): Record<string, string | number | boolean | null> {
  const out: Record<string, string | number | boolean | null> = {}
  for (const field of fields) {
    const raw = values[field.name] ?? ''
    if (field.type === 'checkbox') out[field.name] = raw === 'true'
    else if (field.type === 'number') out[field.name] = raw === '' ? null : Number(raw)
    else out[field.name] = raw.trim() === '' ? null : raw.trim()
  }
  return out
}

function FormFields({
  fields,
  values,
  onChange,
}: {
  fields: FieldDef[]
  values: Values
  onChange: (name: string, value: string) => void
}) {
  const flats = useAllFlats()
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map((field) => {
        const id = `field-${field.name}`
        const value = values[field.name] ?? ''
        const set = (v: string) => {
          onChange(field.name, v)
        }
        if (field.type === 'checkbox') {
          return (
            <label key={field.name} className="flex items-center gap-2 text-sm sm:col-span-2">
              <input
                type="checkbox"
                className="size-4 accent-[var(--accent-strong)]"
                checked={value === 'true'}
                onChange={(e) => {
                  set(String(e.target.checked))
                }}
              />
              {field.label}
            </label>
          )
        }
        const wide = field.type === 'textarea' ? 'sm:col-span-2' : undefined
        let control: ReactNode
        if (field.type === 'select' || field.type === 'flat') {
          const options =
            field.type === 'flat'
              ? (flats.data ?? []).map((f) => ({ value: f.id, label: f.label }))
              : (field.options ?? [])
          control = (
            <Select
              id={id}
              required={field.required}
              value={value}
              onChange={(e) => {
                set(e.target.value)
              }}
            >
              <option value="" disabled={field.required}>
                {field.required ? 'Choose…' : 'None'}
              </option>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )
        } else if (field.type === 'textarea') {
          control = (
            <Textarea
              id={id}
              required={field.required}
              value={value}
              onChange={(e) => {
                set(e.target.value)
              }}
            />
          )
        } else {
          control = (
            <Input
              id={id}
              type={field.type ?? 'text'}
              required={field.required}
              placeholder={field.placeholder}
              autoComplete={field.type === 'password' ? 'new-password' : 'off'}
              value={value}
              onChange={(e) => {
                set(e.target.value)
              }}
            />
          )
        }
        return (
          <Field key={field.name} id={id} label={field.label} hint={field.hint} className={wide}>
            {control}
          </Field>
        )
      })}
    </div>
  )
}

interface FormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  fields: FieldDef[]
  initial: Values
  submitLabel: string
  submit: (values: Values) => Promise<unknown>
  invalidate: string
  success: string
  done?: (result: unknown) => void
}

function FormDialog(props: FormDialogProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent title={props.title} className="sm:max-w-xl">
        {/* Mounted per opening, so each opening starts from `initial`. */}
        {props.open ? <FormBody {...props} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function FormBody({
  onOpenChange,
  fields,
  initial,
  submitLabel,
  submit,
  invalidate,
  success,
  done,
}: FormDialogProps) {
  const [values, setValues] = useState<Values>(initial)
  const action = useAction(submit, {
    invalidate: [[invalidate], ['audit']],
    success,
    onSuccess: (result) => {
      onOpenChange(false)
      done?.(result)
    },
  })
  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    action.mutate(values)
  }
  return (
    <form className="grid gap-5" onSubmit={onSubmit}>
      <FormFields
        fields={fields}
        values={values}
        onChange={(name, value) => {
          setValues((current) => ({ ...current, [name]: value }))
        }}
      />
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button
          variant="secondary"
          onClick={() => {
            onOpenChange(false)
          }}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={action.isPending}>
          {submitLabel}
        </Button>
      </div>
    </form>
  )
}

export function ResourcePage<T extends { id: string }>({ config }: { config: ResourceConfig<T> }) {
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('')
  const [offset, setOffset] = useState(0)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<T | null>(null)

  // Search as you type, but wait for a pause before asking the server.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(q)
      setOffset(0)
    }, 300)
    return () => {
      clearTimeout(timer)
    }
  }, [q])

  const list = useQuery({
    queryKey: [config.key, { search, filter, offset }],
    queryFn: () =>
      config.list({ q: search || undefined, filter: filter || undefined, limit: PAGE, offset }),
    placeholderData: keepPreviousData,
  })

  const remove = useAction((row: T) => config.remove?.submit(row) ?? Promise.resolve(), {
    invalidate: [[config.key], ['audit']],
    success: `${config.singular} deleted`,
  })

  const hasActions = Boolean(config.edit || config.remove || config.rowActions)
  const filtered = Boolean(search || filter)

  return (
    <div>
      <PageHeader title={config.title} description={config.description}>
        {config.create ? (
          <Button
            onClick={() => {
              setCreating(true)
            }}
          >
            <Plus /> Add {config.singular.toLowerCase()}
          </Button>
        ) : null}
      </PageHeader>

      <Card>
        {config.search || config.filter ? (
          <div className="flex flex-wrap gap-2 border-b border-border p-3">
            {config.search ? (
              <div className="relative min-w-56 flex-1">
                <Search
                  className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint"
                  aria-hidden="true"
                />
                <Input
                  aria-label={config.search}
                  placeholder={config.search}
                  className="pl-9"
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value)
                  }}
                />
              </div>
            ) : null}
            {config.filter ? (
              <Select
                aria-label={config.filter.label}
                className="w-auto min-w-40"
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value)
                  setOffset(0)
                }}
              >
                <option value="">{config.filter.label}: all</option>
                {config.filter.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            ) : null}
          </div>
        ) : null}

        {list.isLoading ? <SkeletonRows rows={6} className="p-3" /> : null}
        {list.isError ? (
          <ErrorState error={list.error} onRetry={() => void list.refetch()} className="m-3" />
        ) : null}
        {list.data?.items.length === 0 ? (
          <EmptyState
            icon={Inbox}
            className="m-3"
            title={filtered ? 'Nothing matches' : `No ${config.title.toLowerCase()} yet`}
            action={
              filtered ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setQ('')
                    setFilter('')
                  }}
                >
                  Clear search
                </Button>
              ) : config.create ? (
                <Button
                  size="sm"
                  onClick={() => {
                    setCreating(true)
                  }}
                >
                  Add the first one
                </Button>
              ) : undefined
            }
          >
            {filtered ? 'Try a different search or filter.' : undefined}
          </EmptyState>
        ) : null}
        {list.data && list.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  {config.columns.map((c) => (
                    <Th key={c.header} className={c.className}>
                      {c.header}
                    </Th>
                  ))}
                  {hasActions ? (
                    <Th className="text-right">
                      <span className="sr-only">Actions</span>
                    </Th>
                  ) : null}
                </tr>
              </thead>
              <tbody className={list.isPlaceholderData ? 'opacity-60' : undefined}>
                {list.data.items.map((row) => (
                  <Tr key={row.id}>
                    {config.columns.map((c) => (
                      <Td key={c.header} className={c.className}>
                        {c.cell(row)}
                      </Td>
                    ))}
                    {hasActions ? (
                      <Td className="text-right whitespace-nowrap">
                        {config.rowActions?.(row)}
                        {config.edit ? (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8"
                            aria-label={`Edit ${config.singular.toLowerCase()}`}
                            onClick={() => {
                              setEditing(row)
                            }}
                          >
                            <Pencil />
                          </Button>
                        ) : null}
                        {config.remove ? (
                          <ConfirmDialog
                            trigger={
                              <Button
                                variant="ghost"
                                size="icon"
                                className="size-8 hover:text-danger"
                                aria-label={`Delete ${config.singular.toLowerCase()}`}
                              >
                                <Trash2 />
                              </Button>
                            }
                            title={`Delete this ${config.singular.toLowerCase()}?`}
                            description={config.remove.describe(row)}
                            confirmLabel={`Delete ${config.singular.toLowerCase()}`}
                            onConfirm={() => remove.mutateAsync(row)}
                          />
                        ) : null}
                      </Td>
                    ) : null}
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />
          </>
        ) : null}
      </Card>

      {config.create ? (
        <FormDialog
          open={creating}
          onOpenChange={setCreating}
          title={`Add ${config.singular.toLowerCase()}`}
          fields={config.create.fields}
          initial={{}}
          submitLabel={`Add ${config.singular.toLowerCase()}`}
          submit={config.create.submit}
          invalidate={config.key}
          success={`${config.singular} added`}
          done={config.create.done}
        />
      ) : null}
      {config.edit && editing ? (
        <FormDialog
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null)
          }}
          title={`Edit ${config.singular.toLowerCase()}`}
          fields={config.edit.fields}
          initial={config.edit.initial(editing)}
          submitLabel="Save changes"
          submit={(values) => config.edit?.submit(editing, values) ?? Promise.resolve()}
          invalidate={config.key}
          success="Changes saved"
        />
      ) : null}
    </div>
  )
}
