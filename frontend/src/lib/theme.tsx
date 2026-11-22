import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'
const KEY = 'gatesense.theme'

interface ThemeState {
  /** What the user picked; null = they never picked, so the area's default applies. */
  choice: ThemeChoice | null
  resolved: 'light' | 'dark'
  setChoice: (choice: ThemeChoice) => void
  /** Each area sets its default: the guard console is dark (night shifts), others follow the OS. */
  setAreaDefault: (choice: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeState | null>(null)

function readChoice(): ThemeChoice | null {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'dark' || value === 'system' ? value : null
  } catch {
    return null
  }
}

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice | null>(readChoice)
  const [areaDefault, setAreaDefault] = useState<ThemeChoice>('system')
  const [systemDark, setSystemDark] = useState(systemPrefersDark)

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const update = () => {
      setSystemDark(query.matches)
    }
    query.addEventListener('change', update)
    return () => {
      query.removeEventListener('change', update)
    }
  }, [])

  const effective = choice ?? areaDefault
  const resolved = effective === 'system' ? (systemDark ? 'dark' : 'light') : effective

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [resolved])

  const setChoice = useCallback((next: ThemeChoice) => {
    setChoiceState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // ignore: the choice still applies until the page reloads
    }
  }, [])

  const value = useMemo(
    () => ({ choice, resolved, setChoice, setAreaDefault }),
    [choice, resolved, setChoice],
  )
  return <ThemeContext value={value}>{children}</ThemeContext>
}

export function useTheme(): ThemeState {
  const value = useContext(ThemeContext)
  if (!value) throw new Error('useTheme must be used inside <ThemeProvider>')
  return value
}

/** Call at the top of an area's layout to set that area's default theme. */
export function useAreaTheme(defaultChoice: ThemeChoice): void {
  const { setAreaDefault } = useTheme()
  useEffect(() => {
    setAreaDefault(defaultChoice)
    return () => {
      setAreaDefault('system')
    }
  }, [defaultChoice, setAreaDefault])
}
