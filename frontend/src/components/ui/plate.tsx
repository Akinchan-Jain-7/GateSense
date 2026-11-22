import { cn } from '@/lib/cn'
import { formatPlate } from '@/lib/plates'

const sizes = {
  sm: { plate: 'h-6 text-[13px] pr-1.5', strip: 'w-3 text-[5px]', gap: 'pl-1.5' },
  md: { plate: 'h-8 text-base pr-2.5', strip: 'w-4 text-[6px]', gap: 'pl-2' },
  lg: { plate: 'h-11 text-[22px] pr-3', strip: 'w-5 text-[7px]', gap: 'pl-2.5' },
}

/**
 * An Indian high-security plate (HSRP) in miniature: white plate, black border, blue
 * "IND" strip. It stays white in dark mode, like the real thing. See docs/design.md.
 */
export function Plate({
  plate,
  size = 'md',
  className,
}: {
  plate: string
  size?: keyof typeof sizes
  className?: string
}) {
  const s = sizes[size]
  const text = formatPlate(plate)
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-stretch self-start justify-self-start overflow-hidden rounded-[4px] border-[1.5px] border-[#1b1d21] bg-white leading-none text-[#111317]',
        s.plate,
        className,
      )}
      aria-label={`Plate ${text}`}
      role="img"
    >
      <span
        aria-hidden="true"
        className={cn(
          'flex flex-col items-center justify-end bg-[#1f45c2] pb-0.5 font-sans font-semibold text-white',
          s.strip,
        )}
      >
        IND
      </span>
      <span
        aria-hidden="true"
        className={cn(
          'flex items-center font-plate font-semibold tracking-[0.06em] whitespace-nowrap',
          s.gap,
        )}
      >
        {text}
      </span>
    </span>
  )
}
