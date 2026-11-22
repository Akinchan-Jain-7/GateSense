import { Code, LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Badge, type BadgeTone } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Logo } from '@/components/ui/logo'
import { Plate } from '@/components/ui/plate'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { useAuth } from '@/lib/auth'
import { homeFor } from '@/lib/api/auth'

import { useDemoLogin } from '../auth/useDemoLogin'
import { ArchitectureDiagram } from './ArchitectureDiagram'

const REPO = 'https://github.com/Akinchan-Jain-7/GateSense'

const SAMPLE_FEED: {
  plate: string
  who: string
  flat: string
  time: string
  status: string
  tone: BadgeTone
}[] = [
  {
    plate: 'UP16AB4821',
    who: 'Resident',
    flat: 'B-402',
    time: '6:42 pm',
    status: 'Let in',
    tone: 'ok',
  },
  {
    plate: 'DL3CAF2290',
    who: 'Swiggy order',
    flat: 'C-201',
    time: '6:43 pm',
    status: 'Asking the flat',
    tone: 'accent',
  },
  {
    plate: 'HR26DK8337',
    who: 'Watchlist',
    flat: '',
    time: '6:45 pm',
    status: 'Guard alerted',
    tone: 'danger',
  },
  {
    plate: '22BH6604KM',
    who: 'Guest pass',
    flat: 'A-101',
    time: '6:47 pm',
    status: 'Let in',
    tone: 'ok',
  },
]

const STEPS = [
  {
    title: 'The camera reads the plate',
    body: 'A YOLOv8 detector finds the plate and OCR reads it. Look-alike characters such as O and 0 are fixed by where they sit on an Indian plate.',
  },
  {
    title: 'Known cars go straight in',
    body: 'Residents’ vehicles and guests with a pass are let in and logged. Nobody has to tap anything.',
  },
  {
    title: 'Everyone else waits for the flat',
    body: 'The guard registers the visitor and the flat gets Approve and Deny on the web app and Telegram. No answer in 3 minutes? The guard decides.',
  },
  {
    title: 'Overstays get followed up',
    body: 'At the time limit the visitor and the flat get an email, a reminder 30 minutes later, and after an hour the guard gets a call to make.',
  },
]

const ROLES = [
  {
    role: 'guard',
    title: 'For the guard',
    points: [
      'A dark, high-contrast console for night shifts',
      'Every arrival with its plate snapshot',
      'Register a visitor in one form, in English or Hindi',
      'Alerts for watchlist vehicles and overdue visitors',
    ],
  },
  {
    role: 'resident',
    title: 'For residents',
    points: [
      'Approve or turn away visitors from the phone',
      'Guest passes for expected visitors, by plate or code',
      'Your flat’s visit history',
      'Installs like an app (PWA)',
    ],
  },
  {
    role: 'admin',
    title: 'For the society office',
    points: [
      'Busiest hours, visit length and overstay rate',
      'Flats, residents, vehicles, guards and cameras',
      'A watchlist and an audit log of every change',
      'Time limits and privacy settings',
    ],
  },
] as const

function DemoButton({
  role,
  children,
  primary,
}: {
  role: string
  children: ReactNode
  primary?: boolean
}) {
  const demo = useDemoLogin()
  if (!demo.enabled) return null
  return (
    <Button
      size="lg"
      variant={primary ? 'primary' : 'secondary'}
      disabled={demo.pending !== null}
      onClick={() => void demo.loginAs(role)}
    >
      {demo.pending === role ? <LoaderCircle className="animate-spin" /> : null}
      {children}
    </Button>
  )
}

function SampleFeed() {
  return (
    <div
      className="dark rounded-xl border border-border bg-bg text-text"
      aria-label="Example gate feed"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <p className="font-medium">Main gate</p>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <span className="size-1.5 rounded-full bg-ok" aria-hidden="true" />
          Example feed
        </span>
      </div>
      <ul className="divide-y divide-border">
        {SAMPLE_FEED.map((row, i) => (
          <li
            key={row.plate}
            className="animate-arrive grid grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3.5"
            style={{ animationDelay: `${(250 + i * 550).toString()}ms` }}
          >
            <Plate plate={row.plate} size="md" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{row.who}</p>
              <p className="text-xs text-muted tabular">
                {row.flat ? `${row.flat}, ` : ''}
                {row.time}
              </p>
            </div>
            <Badge tone={row.tone}>{row.status}</Badge>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function Landing() {
  const { user } = useAuth()
  const demo = useDemoLogin()

  return (
    <div className="min-h-dvh bg-bg">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
        <Logo />
        <nav className="flex items-center gap-1" aria-label="Main">
          <Button asChild variant="ghost" size="sm">
            <a href={REPO}>
              <Code /> Source
            </a>
          </Button>
          <ThemeToggle />
          <Button asChild variant="secondary" size="sm">
            {user ? (
              <Link to={homeFor(user.role)}>Open the app</Link>
            ) : (
              <Link to="/login">Sign in</Link>
            )}
          </Button>
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 pt-10 pb-20 sm:px-8 lg:grid-cols-[1.1fr_1fr] lg:pt-20">
          <div>
            <h1 className="max-w-[16ch] text-3xl font-semibold tracking-tight text-balance sm:text-[2.75rem] sm:leading-[1.1]">
              Residents drive in. Visitors wait for a yes.
            </h1>
            <p className="mt-5 max-w-[56ch] text-base text-muted">
              GateSense reads every number plate at a housing society’s gate. Residents’ cars go
              straight in, the flat approves each visitor from their phone, and anyone who overstays
              gets a reminder, then a call from the guard.
            </p>
            {demo.enabled ? (
              <>
                <div className="mt-8 flex flex-wrap gap-3">
                  <DemoButton role="guard" primary>
                    Try the guard console
                  </DemoButton>
                  <DemoButton role="resident">Try the resident app</DemoButton>
                  <DemoButton role="admin">Try the admin dashboard</DemoButton>
                </div>
                <p className="mt-4 text-sm text-muted">
                  The demo society and its people are made up. Every demo account uses the password{' '}
                  <code className="rounded bg-surface-2 px-1.5 py-0.5 text-text">
                    {demo.password}
                  </code>
                  .
                </p>
              </>
            ) : (
              <div className="mt-8 flex gap-3">
                <Button asChild size="lg">
                  <Link to="/login">Sign in</Link>
                </Button>
                <Button asChild size="lg" variant="secondary">
                  <a href={REPO}>Read the source</a>
                </Button>
              </div>
            )}
          </div>
          <SampleFeed />
        </section>

        <section className="border-y border-border bg-surface">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
            <h2 className="text-xl font-semibold">What happens at the gate</h2>
            <ol className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((step, i) => (
                <li key={step.title} className="grid content-start gap-2">
                  <span className="grid size-7 place-items-center rounded-full border border-border-strong text-xs font-semibold text-muted tabular">
                    {(i + 1).toString()}
                  </span>
                  <h3 className="mt-1 font-semibold">{step.title}</h3>
                  <p className="text-sm text-muted">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
          <h2 className="text-xl font-semibold">One system, three screens</h2>
          <div className="mt-8 grid gap-10 md:grid-cols-3 md:gap-8">
            {ROLES.map((item) => (
              <div key={item.role} className="border-l-2 border-accent/40 pl-5">
                <h3 className="font-semibold">{item.title}</h3>
                <ul className="mt-3 grid gap-2 text-sm text-muted">
                  {item.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
                {demo.enabled ? (
                  <button
                    type="button"
                    className="mt-4 text-sm font-medium text-accent hover:underline"
                    onClick={() => void demo.loginAs(item.role)}
                  >
                    Open the {item.role} demo
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-border bg-surface">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">How it’s built</h2>
                <p className="mt-2 max-w-[60ch] text-muted">
                  Plate recognition runs at the gate, so a slow internet link never holds up a car.
                  Everything else is one FastAPI service with background workers, and the web app
                  stays live over a WebSocket.
                </p>
              </div>
              <Button asChild variant="secondary">
                <a href={`${REPO}/blob/main/docs/architecture.md`}>Architecture notes</a>
              </Button>
            </div>
            <div className="mt-8 overflow-x-auto rounded-xl border border-border bg-bg p-4">
              <ArchitectureDiagram />
            </div>
            <p className="mt-6 text-sm text-muted">
              Python 3.12, FastAPI, PostgreSQL, Redis, Celery, YOLOv8 and ONNX Runtime, React with
              TypeScript, Docker and GitHub Actions.
            </p>
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 text-sm text-muted sm:px-8">
        <Logo className="text-muted" />
        <p>
          MIT licensed.{' '}
          <a className="text-accent hover:underline" href={REPO}>
            Source on GitHub
          </a>
        </p>
      </footer>
    </div>
  )
}
