import { LogOut, Send } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { api, unwrap, type Schemas } from '@/lib/api/client'
import { useAuth } from '@/lib/auth'
import { useAction } from '@/lib/queries'

export function ProfilePage() {
  const { user, signOut } = useAuth()
  const [link, setLink] = useState<Schemas['LinkCode'] | null>(null)
  const getCode = useAction(() => unwrap(api.POST('/api/v1/telegram/link-code')), {
    onSuccess: setLink,
  })
  const unlink = useAction(() => unwrap(api.DELETE('/api/v1/telegram/link')), {
    success: 'Telegram disconnected. Approvals now come only to this app.',
  })

  return (
    <div className="grid gap-4">
      <h1 className="text-xl font-semibold">Profile</h1>
      <Card>
        <CardContent className="grid gap-1 pt-4">
          <p className="text-lg font-semibold">{user?.full_name}</p>
          <p className="text-sm text-muted">{user?.email}</p>
          <p className="text-sm text-muted tabular">{user?.phone}</p>
          <p className="text-sm text-muted">Flat {user?.flats.map((f) => f.label).join(', ')}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Approve from Telegram</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <p className="text-sm text-muted">
            Get visitor requests as Telegram messages with Approve and Turn away buttons, even when
            this app is closed.
          </p>
          {link ? (
            <div className="grid gap-2 rounded-lg bg-surface-2 p-3 text-sm">
              {link.link ? (
                <Button asChild>
                  <a href={link.link} target="_blank" rel="noreferrer">
                    <Send /> Open Telegram to connect
                  </a>
                </Button>
              ) : null}
              <p>
                Or send{' '}
                <code className="rounded bg-surface px-1.5 py-0.5 font-semibold">
                  /start {link.code}
                </code>{' '}
                to the society’s bot. The code works for{' '}
                {Math.round(link.expires_in_seconds / 60).toString()} minutes.
              </p>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                disabled={getCode.isPending}
                onClick={() => {
                  getCode.mutate(undefined)
                }}
              >
                <Send /> Connect Telegram
              </Button>
              <Button
                variant="ghost"
                disabled={unlink.isPending}
                onClick={() => {
                  unlink.mutate(undefined)
                }}
              >
                Disconnect
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center justify-between pt-4">
          <p className="text-sm">Theme</p>
          <ThemeToggle />
        </CardContent>
      </Card>

      <Button variant="secondary" size="lg" onClick={() => void signOut()}>
        <LogOut /> Sign out
      </Button>
    </div>
  )
}
