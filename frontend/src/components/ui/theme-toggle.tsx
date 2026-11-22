import { Moon, Sun } from 'lucide-react'

import { useTheme } from '@/lib/theme'

import { Button } from './button'

export function ThemeToggle({ className }: { className?: string }) {
  const { resolved, setChoice } = useTheme()
  const next = resolved === 'dark' ? 'light' : 'dark'
  return (
    <Button
      variant="ghost"
      size="icon"
      className={className}
      aria-label={`Switch to ${next} theme`}
      onClick={() => {
        setChoice(next)
      }}
    >
      {resolved === 'dark' ? <Sun /> : <Moon />}
    </Button>
  )
}
