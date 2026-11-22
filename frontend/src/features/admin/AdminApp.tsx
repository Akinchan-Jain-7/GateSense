import {
  Building2,
  Camera,
  CarFront,
  ClipboardCheck,
  Gauge,
  History,
  LogOut,
  Menu,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Users,
  Footprints,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Logo } from '@/components/ui/logo'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/cn'
import { useAreaTheme } from '@/lib/theme'

import { AuditPage } from './AuditPage'
import { ChecksPage } from './ChecksPage'
import { OverviewPage } from './OverviewPage'
import {
  FlatsPage,
  GatesPage,
  GuardsPage,
  ResidentsPage,
  VehiclesPage,
  WatchlistPage,
} from './resources'
import { SettingsPage } from './SettingsPage'
import { VisitsPage } from './VisitsPage'

const NAV = [
  {
    group: null,
    items: [
      { to: '/admin', label: 'Overview', icon: Gauge },
      { to: '/admin/visits', label: 'Visits', icon: Footprints },
    ],
  },
  {
    group: 'Society',
    items: [
      { to: '/admin/flats', label: 'Flats', icon: Building2 },
      { to: '/admin/residents', label: 'Residents', icon: Users },
      { to: '/admin/vehicles', label: 'Vehicles', icon: CarFront },
      { to: '/admin/guards', label: 'Guards', icon: ShieldCheck },
    ],
  },
  {
    group: 'Gate',
    items: [
      { to: '/admin/gates', label: 'Gates and cameras', icon: Camera },
      { to: '/admin/watchlist', label: 'Watchlist', icon: ShieldAlert },
      { to: '/admin/checks', label: 'Gate checks', icon: ClipboardCheck },
    ],
  },
  {
    group: 'Records',
    items: [
      { to: '/admin/audit', label: 'Audit log', icon: History },
      { to: '/admin/settings', label: 'Settings', icon: Settings },
    ],
  },
]

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Admin" className="grid gap-5">
      {NAV.map((section, i) => (
        <div key={section.group ?? i} className="grid gap-0.5">
          {section.group ? (
            <p className="px-3 pb-1 text-xs font-medium text-faint">{section.group}</p>
          ) : null}
          {section.items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/admin'}
              onClick={onNavigate}
              className={({ isActive }) =>
                cn(
                  'flex h-9 items-center gap-2.5 rounded-lg px-3 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-surface-2 text-text'
                    : 'text-muted hover:bg-surface-2/60 hover:text-text',
                )
              }
            >
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  )
}

function Account() {
  const { user, signOut } = useAuth()
  return (
    <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{user?.full_name}</p>
        <p className="truncate text-xs text-muted">Society admin</p>
      </div>
      <div className="flex">
        <ThemeToggle />
        <Button variant="ghost" size="icon" aria-label="Sign out" onClick={() => void signOut()}>
          <LogOut />
        </Button>
      </div>
    </div>
  )
}

export default function AdminApp() {
  useAreaTheme('system')
  const [menuOpen, setMenuOpen] = useState(false)
  const location = useLocation()

  return (
    <div className="min-h-dvh bg-bg lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-border bg-surface px-3 py-4 lg:flex">
        <Logo className="px-3" />
        <div className="flex-1 overflow-y-auto">
          <Nav />
        </div>
        <Account />
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border bg-surface px-4 py-2.5 lg:hidden">
        <Logo />
        <Button
          variant="ghost"
          size="icon"
          aria-label="Open menu"
          onClick={() => {
            setMenuOpen(true)
          }}
        >
          <Menu />
        </Button>
      </header>
      <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
        <DialogContent title="Menu">
          <Nav
            onNavigate={() => {
              setMenuOpen(false)
            }}
          />
          <div className="mt-5">
            <Account />
          </div>
        </DialogContent>
      </Dialog>

      <main key={location.pathname} className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
        <Routes>
          <Route index element={<OverviewPage />} />
          <Route path="visits" element={<VisitsPage />} />
          <Route path="flats" element={<FlatsPage />} />
          <Route path="residents" element={<ResidentsPage />} />
          <Route path="vehicles" element={<VehiclesPage />} />
          <Route path="guards" element={<GuardsPage />} />
          <Route path="gates" element={<GatesPage />} />
          <Route path="watchlist" element={<WatchlistPage />} />
          <Route path="checks" element={<ChecksPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
