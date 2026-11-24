import { useState, type SubmitEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input, Select } from '@/components/ui/input'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { cn } from '@/lib/cn'
import { cleanPlateInput } from '@/lib/plates'
import { useAction, useAllFlats, type VisitCategory } from '@/lib/queries'

const CATEGORIES: VisitCategory[] = ['guest', 'delivery', 'cab', 'service']

export interface RegisterPrefill {
  plate?: string
  gateEventId?: string
}

export function RegisterVisitorDialog({
  open,
  onOpenChange,
  prefill,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  prefill: RegisterPrefill
}) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t('register.title')} description={t('register.description')}>
        {/* Remount per opening so the form starts fresh with the new prefill. */}
        {open ? (
          <RegisterForm
            prefill={prefill}
            onDone={() => {
              onOpenChange(false)
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function RegisterForm({ prefill, onDone }: { prefill: RegisterPrefill; onDone: () => void }) {
  const { t } = useTranslation()
  const flats = useAllFlats()
  const [form, setForm] = useState({
    full_name: '',
    phone: '',
    email: '',
    flat_id: '',
    plate: prefill.plate ?? '',
    category: 'guest' as VisitCategory,
    purpose: '',
    duration_minutes: '60',
  })
  const set = (key: keyof typeof form) => (value: string) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const register = useAction(
    (body: Schemas['VisitorRegistration']) => unwrap(api.POST('/api/v1/visits', { body })),
    {
      // gate-events too: the arrival this visit was linked to stops offering "Register".
      invalidate: [['visits'], ['approvals'], ['gate-events']],
      success: (result) =>
        t('register.sent', {
          flat: result.visit.flat_label,
          name: result.visit.visitor_name ?? form.full_name,
        }),
      onSuccess: onDone,
    },
  )

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    register.mutate({
      full_name: form.full_name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim() || null,
      flat_id: form.flat_id,
      plate: cleanPlateInput(form.plate) || null,
      category: form.category,
      purpose: form.purpose.trim() || null,
      duration_minutes: form.category === 'service' ? Number(form.duration_minutes) : null,
      gate_event_id: prefill.gateEventId ?? null,
    })
  }

  return (
    <form className="grid gap-4" onSubmit={submit}>
      <fieldset className="grid gap-1.5">
        <legend className="mb-1.5 text-sm font-medium">{t('register.category')}</legend>
        <div className="grid grid-cols-4 gap-1 rounded-lg border border-border p-1">
          {CATEGORIES.map((category) => (
            <label
              key={category}
              className={cn(
                'flex h-11 cursor-pointer items-center justify-center rounded-md text-sm font-medium text-muted has-[:checked]:bg-accent-soft has-[:checked]:text-accent has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent',
              )}
            >
              <input
                type="radio"
                name="category"
                value={category}
                checked={form.category === category}
                onChange={() => {
                  set('category')(category)
                }}
                className="sr-only"
              />
              {t(`category.${category}`)}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="visitor-name" label={t('register.name')}>
          <Input
            id="visitor-name"
            required
            minLength={2}
            autoComplete="off"
            className="h-12"
            value={form.full_name}
            onChange={(e) => {
              set('full_name')(e.target.value)
            }}
          />
        </Field>
        <Field id="visitor-phone" label={t('register.phone')}>
          <Input
            id="visitor-phone"
            required
            type="tel"
            inputMode="tel"
            placeholder="98765 43210"
            className="h-12"
            value={form.phone}
            onChange={(e) => {
              set('phone')(e.target.value)
            }}
          />
        </Field>
        <Field id="visitor-flat" label={t('register.flat')}>
          <Select
            id="visitor-flat"
            required
            className="h-12"
            value={form.flat_id}
            onChange={(e) => {
              set('flat_id')(e.target.value)
            }}
          >
            <option value="" disabled>
              {flats.isLoading ? '…' : t('register.chooseFlat')}
            </option>
            {flats.data?.map((flat) => (
              <option key={flat.id} value={flat.id}>
                {flat.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field id="visitor-plate" label={t('register.plate')}>
          <Input
            id="visitor-plate"
            autoComplete="off"
            className="h-12 uppercase"
            placeholder="UP16 AB 1234"
            value={form.plate}
            onChange={(e) => {
              set('plate')(e.target.value)
            }}
          />
        </Field>
      </div>
      {form.category === 'service' ? (
        <Field id="visitor-duration" label={t('register.duration')}>
          <Input
            id="visitor-duration"
            type="number"
            min={10}
            max={1440}
            step={10}
            className="h-12"
            value={form.duration_minutes}
            onChange={(e) => {
              set('duration_minutes')(e.target.value)
            }}
          />
        </Field>
      ) : null}
      <Field id="visitor-purpose" label={t('register.purpose')}>
        <Input
          id="visitor-purpose"
          className="h-12"
          value={form.purpose}
          onChange={(e) => {
            set('purpose')(e.target.value)
          }}
        />
      </Field>
      <Field id="visitor-email" label={t('register.email')} hint={t('register.emailHint')}>
        <Input
          id="visitor-email"
          type="email"
          className="h-12"
          value={form.email}
          onChange={(e) => {
            set('email')(e.target.value)
          }}
        />
      </Field>
      <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" size="xl" onClick={onDone}>
          {t('register.cancel')}
        </Button>
        <Button type="submit" size="xl" disabled={register.isPending}>
          {t('register.submit')}
        </Button>
      </div>
    </form>
  )
}
