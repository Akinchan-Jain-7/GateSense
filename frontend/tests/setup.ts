import '@testing-library/jest-dom/vitest'
import '../src/i18n'

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

import { setTokens } from '../src/lib/api/tokens'

// jsdom has no matchMedia; the theme and layout hooks need it.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }),
})

// ResizeObserver is used by Recharts and Radix.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal('ResizeObserver', ResizeObserverStub)

afterEach(() => {
  cleanup()
  setTokens(null) // the token module keeps a copy in memory: don't leak a login between tests
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.stubGlobal('ResizeObserver', ResizeObserverStub)
})
