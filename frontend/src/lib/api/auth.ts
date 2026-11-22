import { API_BASE, ApiError, errorMessage, type Schemas } from './client'
import { getTokens, setTokens } from './tokens'

export type Role = Schemas['UserRole']

/** Sign in with email + password (the API uses the OAuth2 password form). */
export async function signIn(email: string, password: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }),
    })
  } catch {
    throw new ApiError(0, errorMessage(null, 0))
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, response.status))
  const tokens = body as Schemas['TokenResponse']
  setTokens({ access: tokens.access_token, refresh: tokens.refresh_token })
}

export async function signOut(): Promise<void> {
  const tokens = getTokens()
  setTokens(null)
  if (!tokens) return
  // Revoke the refresh token on the server; signing out locally doesn't wait for it.
  await fetch(`${API_BASE}/api/v1/auth/logout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: tokens.refresh }),
  }).catch(() => undefined)
}

export function homeFor(role: Role): string {
  return { admin: '/admin', guard: '/guard', resident: '/resident' }[role]
}
