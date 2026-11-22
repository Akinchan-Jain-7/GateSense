import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'

import { cn } from '@/lib/cn'

export const buttonVariants = cva(
  'inline-flex shrink-0 items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-accent-strong text-accent-fg hover:bg-accent-strong/90',
        secondary: 'border border-border bg-surface text-text hover:bg-surface-2',
        ghost: 'text-muted hover:bg-surface-2 hover:text-text',
        approve: 'bg-ok text-white hover:bg-ok/90 dark:text-[#0d1f14]',
        danger: 'bg-danger text-white hover:bg-danger/90 dark:text-[#2a0c0a]',
        'danger-outline': 'border border-danger/40 text-danger hover:bg-danger-soft',
      },
      size: {
        sm: 'h-8 px-3 text-xs',
        md: 'h-10 px-4 text-sm',
        lg: 'h-12 px-5 text-base',
        // Guard console: big targets for gloves, hurry and night shifts.
        xl: 'h-14 px-6 text-base [&_svg]:size-5',
        icon: 'size-10',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export type ButtonProps = ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }

export function Button({ className, variant, size, asChild = false, type, ...props }: ButtonProps) {
  const Component = asChild ? Slot : 'button'
  return (
    <Component
      className={cn(buttonVariants({ variant, size }), className)}
      type={asChild ? undefined : (type ?? 'button')}
      {...props}
    />
  )
}
