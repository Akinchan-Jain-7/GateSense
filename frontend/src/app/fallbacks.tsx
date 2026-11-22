import { Compass } from 'lucide-react'
import { Link, useRouteError } from 'react-router'

import { Button } from '@/components/ui/button'
import { Logo } from '@/components/ui/logo'
import { Skeleton } from '@/components/ui/skeleton'

export function FullPageLoader() {
  return (
    <div className="grid min-h-dvh place-items-center" role="status" aria-label="Loading">
      <div className="grid w-64 gap-3">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-24" />
        <Skeleton className="h-4 w-48" />
      </div>
    </div>
  )
}

function Centered({ title, body }: { title: string; body: string }) {
  return (
    <main className="grid min-h-dvh place-items-center px-6">
      <div className="grid max-w-md gap-4 text-center">
        <Logo className="justify-self-center" />
        <Compass className="size-6 justify-self-center text-faint" aria-hidden="true" />
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="text-muted">{body}</p>
        <Button asChild className="justify-self-center">
          <Link to="/">Go to the home page</Link>
        </Button>
      </div>
    </main>
  )
}

export function NotFound() {
  return (
    <Centered
      title="This page doesn’t exist"
      body="Check the address, or start from the home page."
    />
  )
}

export function RouteError() {
  const error = useRouteError()
  console.error(error)
  return (
    <Centered
      title="This screen hit an error"
      body="Reload the page. If it keeps happening, the error is in the browser console."
    />
  )
}
