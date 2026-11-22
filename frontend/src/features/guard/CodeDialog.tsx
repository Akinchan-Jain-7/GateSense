import { useState, type SubmitEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { api, unwrap } from '@/lib/api/client'
import { useAction } from '@/lib/queries'

export function CodeDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [code, setCode] = useState('')
  const redeem = useAction(
    (value: string) => unwrap(api.POST('/api/v1/guest-passes/redeem', { body: { code: value } })),
    {
      invalidate: [['visits']],
      success: (visit) => t('code.admitted', { name: visit.visitor_name ?? '' }),
      onSuccess: () => {
        setCode('')
        onOpenChange(false)
      },
    },
  )

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    redeem.mutate(code.replace(/\s/g, '').toUpperCase())
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t('code.title')} description={t('code.description')}>
        <form className="grid gap-4" onSubmit={submit}>
          <Field id="pass-code" label={t('code.label')}>
            <Input
              id="pass-code"
              required
              minLength={6}
              maxLength={12}
              autoComplete="off"
              autoCapitalize="characters"
              className="h-14 text-center font-plate text-2xl tracking-[0.3em] uppercase"
              value={code}
              onChange={(e) => {
                setCode(e.target.value)
              }}
            />
          </Field>
          <Button type="submit" size="xl" disabled={redeem.isPending || code.trim().length < 6}>
            {t('code.submit')}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
