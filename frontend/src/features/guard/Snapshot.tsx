import { useQuery } from '@tanstack/react-query'
import { ImageOff } from 'lucide-react'
import { useEffect, useMemo } from 'react'

import { Dialog, DialogContent, DialogTrigger } from '@/components/ui/dialog'
import { API_BASE, authFetch } from '@/lib/api/client'
import { cn } from '@/lib/cn'

/**
 * Plate snapshots need the guard's token, so an <img src> can't load them directly:
 * fetch the bytes with the token and show them through a temporary object URL.
 */
function useSnapshotUrl(eventId: string): string | null | undefined {
  const blob = useQuery({
    queryKey: ['snapshot', eventId],
    queryFn: async () => {
      const response = await authFetch(
        new Request(`${API_BASE || window.location.origin}/api/v1/gate-events/${eventId}/snapshot`),
      )
      if (!response.ok) throw new Error('No snapshot')
      return response.blob()
    },
    staleTime: Infinity,
    retry: false,
  })
  const url = useMemo(() => (blob.data ? URL.createObjectURL(blob.data) : null), [blob.data])
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url)
    },
    [url],
  )
  if (blob.isError) return null
  return url ?? undefined
}

export function Snapshot({
  eventId,
  alt,
  className,
}: {
  eventId: string
  alt: string
  className?: string
}) {
  const url = useSnapshotUrl(eventId)
  const frame = cn('overflow-hidden rounded-lg border border-border bg-surface-2', className)
  if (url === null) {
    return (
      <span className={cn(frame, 'grid place-items-center text-faint')}>
        <ImageOff className="size-4" aria-label="Snapshot unavailable" />
      </span>
    )
  }
  if (url === undefined) return <span className={cn(frame, 'animate-pulse')} aria-hidden="true" />
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button type="button" className={frame} aria-label={`${alt}: enlarge`}>
          <img src={url} alt={alt} className="size-full object-cover" />
        </button>
      </DialogTrigger>
      <DialogContent title={alt} className="sm:max-w-2xl">
        <img src={url} alt={alt} className="w-full rounded-lg" />
      </DialogContent>
    </Dialog>
  )
}
