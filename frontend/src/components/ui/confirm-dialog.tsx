import { useState, type ReactNode } from 'react'

import { Button } from './button'
import { Dialog, DialogContent, DialogTrigger } from './dialog'

/** Ask before anything destructive. The confirm button names the action ("Delete flat"). */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  trigger: ReactNode
  title: string
  description: ReactNode
  confirmLabel: string
  onConfirm: () => Promise<unknown>
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      {/* alertdialog: screen readers announce it as a question that needs an answer now. */}
      <DialogContent role="alertdialog" title={title} description={description}>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button
            variant="secondary"
            onClick={() => {
              setOpen(false)
            }}
          >
            Keep it
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              setBusy(true)
              onConfirm()
                .then(() => {
                  setOpen(false)
                })
                .catch(() => undefined) // the caller shows the error toast
                .finally(() => {
                  setBusy(false)
                })
            }}
          >
            {confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
