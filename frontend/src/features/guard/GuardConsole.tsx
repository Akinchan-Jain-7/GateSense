import { useQuery } from '@tanstack/react-query'
import { KeyRound, Languages, LogOut, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Logo } from '@/components/ui/logo'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { setLanguage } from '@/i18n'
import { api, unwrap } from '@/lib/api/client'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { useLive, useLiveStatus } from '@/lib/live'
import type { Alert, Approval, Escalation } from '@/lib/queries'
import { useAreaTheme } from '@/lib/theme'
import { useMediaQuery } from '@/lib/useMediaQuery'

import { AlertsColumn, ArrivalsColumn, InsideColumn, WaitingColumn } from './columns'
import { CodeDialog } from './CodeDialog'
import { RegisterVisitorDialog, type RegisterPrefill } from './RegisterVisitorDialog'

function LiveIndicator() {
  const { t } = useTranslation()
  const status = useLiveStatus()
  const label = {
    live: t('console.live'),
    connecting: t('console.connecting'),
    reconnecting: t('console.reconnecting'),
  }[status]
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-muted" role="status">
      <span
        aria-hidden="true"
        className={cn('size-2 rounded-full', status === 'live' ? 'bg-ok' : 'animate-pulse bg-warn')}
      />
      {label}
    </span>
  )
}

function InsideCounter() {
  const { t } = useTranslation()
  const inside = useQuery({
    queryKey: ['visits', 'inside-count'],
    queryFn: () => unwrap(api.GET('/api/v1/analytics/inside')),
    refetchInterval: 60_000,
  })
  return (
    <div className="flex h-12 items-center gap-2 rounded-xl border border-border bg-surface px-3 lg:h-14 lg:px-4">
      <span className="text-2xl font-semibold tabular">
        {inside.data ? inside.data.vehicles_inside.toString() : '–'}
      </span>
      <span className="text-xs leading-tight text-muted lg:text-sm">
        {t('console.vehiclesInside')}
        {inside.data ? (
          <span className="hidden lg:inline">
            {' '}
            ({t('console.visitorsInside', { count: inside.data.visitors_inside })})
          </span>
        ) : null}
      </span>
    </div>
  )
}

function LanguageButton({ compact = false }: { compact?: boolean }) {
  const { t, i18n } = useTranslation()
  const next = i18n.language === 'hi' ? 'en' : 'hi'
  return (
    <Button
      size={compact ? 'md' : 'xl'}
      variant="ghost"
      className={compact ? 'h-11 px-3' : undefined}
      lang={next}
      aria-label={t('console.switchLanguageLabel')}
      onClick={() => {
        setLanguage(next)
      }}
    >
      <Languages /> {t('console.switchLanguage')}
    </Button>
  )
}

function SignOutButton({
  className,
  label,
  onClick,
}: {
  className: string
  label: string
  onClick: () => void
}) {
  return (
    <Button size="icon" variant="ghost" className={className} aria-label={label} onClick={onClick}>
      <LogOut />
    </Button>
  )
}

export default function GuardConsole() {
  useAreaTheme('dark') // night shifts: dark unless the guard picks otherwise
  const { t, i18n } = useTranslation()
  const { user, signOut } = useAuth()
  const [registerOpen, setRegisterOpen] = useState(false)
  const [prefill, setPrefill] = useState<RegisterPrefill>({})
  const [codeOpen, setCodeOpen] = useState(false)

  const openRegister = (values: RegisterPrefill = {}) => {
    setPrefill(values)
    setRegisterOpen(true)
  }

  useLive((message) => {
    if (message.type === 'alert.created') {
      toast.error(t('alerts.watchlist'), {
        description: (message.data as Alert).message,
        duration: 10_000,
      })
    } else if (message.type === 'escalation.created') {
      const task = message.data as Escalation
      toast.warning(t('alerts.callResident', { flat: task.visit.flat_label }))
    } else if (message.type === 'approval.timed_out') {
      const approval = message.data as Approval
      toast.warning(t('waiting.noAnswer'), {
        description: approval.visit.visitor_name ?? undefined,
      })
    }
  })

  const wide = useMediaQuery('(min-width: 1024px)')

  return (
    <div lang={i18n.language} className="flex h-dvh flex-col bg-bg text-text">
      <header className="grid gap-3 border-b border-border px-4 py-3 lg:flex lg:flex-wrap lg:items-center lg:px-6">
        <div className="flex items-center gap-3">
          <Logo markOnly />
          <div>
            <h1 className="text-base leading-tight font-semibold">{t('console.title')}</h1>
            <p className="text-xs text-muted">{user?.full_name}</p>
          </div>
          <LiveIndicator />
          <div className="ml-auto flex items-center gap-1 lg:hidden">
            <LanguageButton compact />
            <ThemeToggle className="size-11" />
            <SignOutButton
              className="size-11"
              onClick={() => void signOut()}
              label={t('console.signOut')}
            />
          </div>
        </div>
        <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2 lg:ml-auto lg:flex">
          <InsideCounter />
          <Button
            size={wide ? 'xl' : 'lg'}
            className="h-12 lg:h-14"
            onClick={() => {
              openRegister()
            }}
          >
            <UserPlus /> {t('console.registerVisitor')}
          </Button>
          <Button
            size={wide ? 'xl' : 'lg'}
            variant="secondary"
            className="h-12 lg:h-14"
            aria-label={t('console.checkCode')}
            onClick={() => {
              setCodeOpen(true)
            }}
          >
            <KeyRound /> <span className="hidden lg:inline">{t('console.checkCode')}</span>
          </Button>
          {wide ? (
            <>
              <LanguageButton />
              <ThemeToggle className="size-14" />
              <SignOutButton
                className="size-14"
                onClick={() => void signOut()}
                label={t('console.signOut')}
              />
            </>
          ) : null}
        </div>
      </header>

      {wide ? (
        /* Wide screens: everything at once. */
        <main className="grid min-h-0 flex-1 grid-cols-[1.25fr_1fr_1fr] gap-4 px-6 pt-4">
          <ArrivalsColumn onRegister={openRegister} />
          <WaitingColumn />
          <div className="grid min-h-0 grid-rows-[auto_1fr] gap-4 overflow-y-auto">
            <AlertsColumn className="min-h-0" />
            <InsideColumn className="min-h-0" />
          </div>
        </main>
      ) : (
        /* Phones and tablets: one column at a time. */
        <Tabs defaultValue="arrivals" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-4 mt-3 grid grid-cols-4">
            <TabsTrigger value="arrivals" className="h-11">
              {t('console.arrivals')}
            </TabsTrigger>
            <TabsTrigger value="waiting" className="h-11">
              {t('console.waitingTab')}
            </TabsTrigger>
            <TabsTrigger value="alerts" className="h-11">
              {t('console.alertsTab')}
            </TabsTrigger>
            <TabsTrigger value="inside" className="h-11">
              {t('console.insideTab')}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="arrivals" className="min-h-0 flex-1 overflow-y-auto px-4 pt-4">
            <ArrivalsColumn onRegister={openRegister} />
          </TabsContent>
          <TabsContent value="waiting" className="min-h-0 flex-1 overflow-y-auto px-4 pt-4">
            <WaitingColumn />
          </TabsContent>
          <TabsContent value="alerts" className="min-h-0 flex-1 overflow-y-auto px-4 pt-4">
            <AlertsColumn />
          </TabsContent>
          <TabsContent value="inside" className="min-h-0 flex-1 overflow-y-auto px-4 pt-4">
            <InsideColumn />
          </TabsContent>
        </Tabs>
      )}

      <RegisterVisitorDialog open={registerOpen} onOpenChange={setRegisterOpen} prefill={prefill} />
      <CodeDialog open={codeOpen} onOpenChange={setCodeOpen} />
    </div>
  )
}
