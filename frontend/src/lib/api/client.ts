/**
 * The typed API client. Paths, parameters and response shapes come from
 * `schema.d.ts`, which is generated from the backend's OpenAPI schema
 * (`npm run api:types`), so a renamed field breaks the build instead of the page.
 *
 * Every request carries the access token. On a 401 we try the refresh token once; if
 * that fails too, the user is signed out.
 */
import createClient from 'openapi-fetch'

import type { components, paths } from './schema'
import { getTokens, setTokens } from './tokens'

export type Schemas = components['schemas']

export const API_BASE: string = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ValidationIssue {
  loc?: (string | number)[]
  msg?: string
}

/** FastAPI errors are `{detail: "text"}` or, for 422, a list of field problems. */
export function errorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return (detail as ValidationIssue[])
      .map((issue) => {
        const field = issue.loc?.filter((part) => part !== 'body').join('.')
        const text = (issue.msg ?? 'is invalid').replace(/^Value error, /, '')
        return field ? `${field}: ${text}` : text
      })
      .join('; ')
  }
  if (status === 0) return 'Can’t reach the server. Check your connection and try again.'
  return `The server returned an error (${status.toString()}). Try again in a moment.`
}

let refreshing: Promise<boolean> | null = null

async function refreshTokens(): Promise<boolean> {
  const tokens = getTokens()
  if (!tokens) return false
  try {
    const response = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: tokens.refresh }),
    })
    if (!response.ok) return false
    const data = (await response.json()) as Schemas['TokenResponse']
    setTokens({ access: data.access_token, refresh: data.refresh_token })
    return true
  } catch {
    return false
  }
}

/** Refresh once even when several requests fail with 401 at the same time. */
export function refreshOnce(): Promise<boolean> {
  refreshing ??= refreshTokens().finally(() => {
    refreshing = null
  })
  return refreshing
}

function withToken(request: Request): Request {
  const tokens = getTokens()
  if (!tokens) return request
  const headers = new Headers(request.headers)
  headers.set('Authorization', `Bearer ${tokens.access}`)
  return new Request(request, { headers })
}

export async function authFetch(request: Request): Promise<Response> {
  const retry = request.clone()
  const response = await fetch(withToken(request))
  const isAuthCall = request.url.includes('/api/v1/auth/')
  if (response.status !== 401 || isAuthCall || !getTokens()) return response
  if (await refreshOnce()) return fetch(withToken(retry))
  setTokens(null)
  return response
}

export const api = createClient<paths>({ baseUrl: API_BASE, fetch: authFetch })

/** Turn an openapi-fetch result into data, or throw an ApiError with a readable message. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response }
  try {
    result = await call
  } catch {
    throw new ApiError(0, errorMessage(null, 0))
  }
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, errorMessage(result.error, result.response.status))
  }
  return result.data as T
}
