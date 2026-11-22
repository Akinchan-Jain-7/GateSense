import { cn } from '@/lib/cn'

/**
 * A row of mutually exclusive choices that filter what's on the page (e.g. a time range).
 * It looks like tabs, but tabs promise a panel per choice; this is a group of toggle
 * buttons instead, so screen readers announce "7 days, pressed" and nothing points at a
 * panel that doesn't exist.
 */
export function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
  className,
}: {
  label: string
  options: readonly { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
  className?: string
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn('inline-flex gap-1 rounded-lg border border-border bg-surface p-1', className)}
    >
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={selected}
            onClick={() => {
              onChange(option.value)
            }}
            className={cn(
              'inline-flex h-8 items-center rounded-md px-3 text-sm font-medium text-muted transition-colors hover:text-text',
              selected && 'bg-surface-2 text-text',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
