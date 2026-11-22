import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import type { APIRequestContext, Browser, Page } from '@playwright/test'

export const PASSWORD = 'GateSense@123'
export const EMAILS = {
  guard: 'guard@example.com',
  resident: 'resident@example.com',
  admin: 'admin@example.com',
}
type Role = keyof typeof EMAILS

export async function tokens(request: APIRequestContext, role: Role) {
  const response = await request.post('/api/v1/auth/login', {
    form: { username: EMAILS[role], password: PASSWORD },
  })
  if (!response.ok()) throw new Error(`login as ${role} failed: ${String(response.status())}`)
  const body = (await response.json()) as { access_token: string; refresh_token: string }
  return { access: body.access_token, refresh: body.refresh_token }
}

/** A browser page already signed in as `role` (tokens put straight into storage). */
export async function pageAs(
  browser: Browser,
  request: APIRequestContext,
  role: Role,
  path: string,
): Promise<Page> {
  const pair = await tokens(request, role)
  const context = await browser.newContext()
  await context.addInitScript((value) => {
    localStorage.setItem('gatesense.tokens', value)
    localStorage.setItem('gatesense.lang', 'en')
  }, JSON.stringify(pair))
  const page = await context.newPage()
  await page.goto(path)
  return page
}

export async function adminGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const { access } = await tokens(request, 'admin')
  const response = await request.get(path, { headers: { Authorization: `Bearer ${access}` } })
  return (await response.json()) as T
}

/** Rotate a camera's key (the test acts as that camera). */
export async function cameraKey(request: APIRequestContext, name: string): Promise<string> {
  const { access } = await tokens(request, 'admin')
  const headers = { Authorization: `Bearer ${access}` }
  const devices = (await (await request.get('/api/v1/devices?limit=100', { headers })).json()) as {
    items: { id: string; name: string }[]
  }
  const device = devices.items.find((d) => d.name === name)
  if (!device) throw new Error(`no camera called ${name}`)
  const rotated = (await (
    await request.post(`/api/v1/devices/${device.id}/rotate-key`, { headers })
  ).json()) as { api_key: string }
  return rotated.api_key
}

export async function sendRead(
  request: APIRequestContext,
  key: string,
  plate: string,
  confidence = 0.96,
) {
  const response = await request.post('/api/v1/gate-events', {
    headers: { 'X-Device-Key': key },
    multipart: {
      plate_text: plate,
      confidence: String(confidence),
      captured_at: new Date().toISOString(),
    },
  })
  if (!response.ok())
    throw new Error(`gate event rejected: ${String(response.status())} ${await response.text()}`)
  return (await response.json()) as { event: { id: string; match_result: string } }
}

const backend = fileURLToPath(new URL('../../backend', import.meta.url))

/** Run a backend set-up script (see backend/tests/e2e_fixtures.py). */
export function fixture(...args: string[]): string {
  return execFileSync('uv', ['run', 'python', '-m', 'tests.e2e_fixtures', ...args], {
    cwd: backend,
    encoding: 'utf8',
  }).trim()
}
