import { LoaderCircle } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Logo } from '@/components/ui/logo'
import { homeFor } from '@/lib/api/auth'
import { useAuth } from '@/lib/auth'

import { useDemoLogin } from './useDemoLogin'

const ROLE_NAMES: Record<string, string> = {
  guard: 'Guard',
  resident: 'Resident',
  admin: 'Admin',
}

/** Only follow `next` to our own pages, never to another site. */
function safeNext(next: string | null): string | null {
  return next?.startsWith('/') && !next.startsWith('//') ? next : null
}

export default function Login() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const demo = useDemoLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const next = safeNext(params.get('next'))
  if (user) return <Navigate to={next ?? homeFor(user.role)} replace />

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const signedIn = await signIn(email.trim(), password)
      const home = homeFor(signedIn.role)
      void navigate(next?.startsWith(home) ? next : home, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t sign in.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-bg px-5 py-10">
      <div className="grid w-full max-w-sm gap-6">
        <Link to="/" className="justify-self-center">
          <Logo />
        </Link>
        <Card className="p-6">
          <h1 className="text-lg font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-muted">Use the email your society office gave you.</p>
          <form className="mt-6 grid gap-4" onSubmit={(e) => void submit(e)} noValidate>
            <Field id="email" label="Email">
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value)
                }}
              />
            </Field>
            <Field id="password" label="Password" error={error}>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'password-error' : undefined}
                onChange={(e) => {
                  setPassword(e.target.value)
                }}
              />
            </Field>
            <Button type="submit" size="lg" disabled={busy || !email || !password}>
              {busy ? <LoaderCircle className="animate-spin" /> : null}
              Sign in
            </Button>
          </form>
        </Card>
        {demo.enabled ? (
          <div className="grid gap-3">
            <p className="text-center text-sm text-muted">Or open the demo as</p>
            <div className="grid grid-cols-3 gap-2">
              {demo.accounts.map((account) => (
                <Button
                  key={account.role}
                  variant="secondary"
                  disabled={demo.pending !== null}
                  onClick={() => void demo.loginAs(account.role)}
                >
                  {demo.pending === account.role ? <LoaderCircle className="animate-spin" /> : null}
                  {ROLE_NAMES[account.role] ?? account.role}
                </Button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </main>
  )
}
