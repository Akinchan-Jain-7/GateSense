import { cn } from '@/lib/cn'

export function Logo({ className, markOnly = false }: { className?: string; markOnly?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2 font-semibold text-text', className)}>
      <svg viewBox="0 0 32 32" className="size-6" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#2147C9" />
        <rect x="5" y="10" width="22" height="12" rx="2" fill="#fff" />
        <rect x="5" y="10" width="5" height="12" rx="2" fill="#7A97FF" />
        <rect x="8" y="10" width="2" height="12" fill="#7A97FF" />
        <path d="M13 14.5h10M13 17.5h7" stroke="#15181D" strokeWidth="2" strokeLinecap="round" />
      </svg>
      {markOnly ? <span className="sr-only">GateSense</span> : 'GateSense'}
    </span>
  )
}
