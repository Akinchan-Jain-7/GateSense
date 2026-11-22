import { useQueryClient } from '@tanstack/react-query'
import { BellRing, History, Ticket, UserRound } from 'lucide-react'
import { NavLink, Route, Routes } from 'react-router'
import { toast } from 'sonner'

import { Logo } from '@/components/ui/logo'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { useLive } from '@/lib/live'
import { useApprovals, type Approval } from '@/lib/queries'
import { useAreaTheme } from '@/lib/theme'

import { ApprovalsPage } from './ApprovalsPage'
import { HistoryPage } from './HistoryPage'
import { PassesPage } from './PassesPage'
import { ProfilePage } from './ProfilePage'

function Tab({
  to,
  icon: Icon,
  label,
  badge,
}: {
  to: string
  icon: typeof Ticket
  label: string
  badge?: number
}) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        cn(
          'relative flex flex-1 flex-col items-center gap-1 pt-2 pb-1 text-xs font-medium',
          isActive ? 'text-accent' : 'text-muted hover:text-text',
        )
      }
    >
      <Icon className="size-5" aria-hidden="true" />
      {label}
      {badge ? (
        <span className="absolute top-1 left-1/2 ml-2 min-w-4 rounded-full bg-danger px-1 text-center text-[10px] leading-4 text-white tabular">
          {badge.toString()}
          <span className="sr-only"> waiting</span>
        </span>
      ) : null}
    </NavLink>
  )
}

export default function ResidentApp() {
  useAreaTheme('system')
  const { user } = useAuth()
  const client = useQueryClient()
  const pending = useApprovals('pending')
  const waiting = pending.data?.items.length ?? 0

  useLive((message) => {
    if (message.type === 'approval.requested') {
      const approval = message.data as Approval
      toast(`${approval.visit.visitor_name ?? 'A visitor'} is at the gate`, {
        description: 'Approve or turn them away on the Approvals tab.',
      })
      void client.invalidateQueries({ queryKey: ['approvals'] })
    }
  })

  const flats = user?.flats.map((f) => f.label).join(', ')

  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col bg-bg">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-bg/95 px-4 py-3 backdrop-blur">
        <Logo />
        <p className="text-sm text-muted">
          {user?.full_name}
          {flats ? (
            <span className="ml-2 rounded-md bg-surface-2 px-1.5 py-0.5 text-text tabular">
              {flats}
            </span>
          ) : null}
        </p>
      </header>
      <main className="flex-1 px-4 pt-4 pb-24">
        <Routes>
          <Route index element={<ApprovalsPage />} />
          <Route path="passes" element={<PassesPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="profile" element={<ProfilePage />} />
        </Routes>
      </main>
      <nav
        aria-label="Resident"
        className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)]"
      >
        <div className="mx-auto flex max-w-xl">
          <Tab to="/resident" icon={BellRing} label="Approvals" badge={waiting} />
          <Tab to="/resident/passes" icon={Ticket} label="Guest passes" />
          <Tab to="/resident/history" icon={History} label="History" />
          <Tab to="/resident/profile" icon={UserRound} label="Profile" />
        </div>
      </nav>
    </div>
  )
}
