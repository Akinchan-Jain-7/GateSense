/**
 * Where the signed-in user's tokens live: localStorage, so a refresh of the page (or the
 * resident PWA reopening) keeps them signed in.
 *
 * Trade-off: any script running on our origin could read localStorage. We accept that for
 * a demo-first product because the API uses bearer tokens; the mitigations are a strict
 * Content-Security-Policy (Phase 7), short-lived access tokens and rotating refresh tokens.
 */

const KEY = 'gatesense.tokens'

export interface Tokens {
  access: string
  refresh: string
}

type Listener = (tokens: Tokens | null) => void
const listeners = new Set<Listener>()

function read(): Tokens | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Tokens>
    return parsed.access && parsed.refresh
      ? { access: parsed.access, refresh: parsed.refresh }
      : null
  } catch {
    return null
  }
}

let current: Tokens | null = read()

export function getTokens(): Tokens | null {
  return current
}

export function setTokens(tokens: Tokens | null): void {
  current = tokens
  try {
    if (tokens) localStorage.setItem(KEY, JSON.stringify(tokens))
    else localStorage.removeItem(KEY)
  } catch {
    // Private mode or storage full: keep the session in memory only.
  }
  for (const listener of listeners) listener(tokens)
}

export function onTokensChange(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
