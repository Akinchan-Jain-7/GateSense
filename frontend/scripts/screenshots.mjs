// Screenshots of every main screen for docs/assets (and for reviewing the UI).
//
//   1. Start the stack in demo mode: API with DEMO_MODE=true, `npm run dev`.
//   2. node scripts/screenshots.mjs [baseUrl] [outDir]
//
// Uses the system Chrome when Playwright's own browser isn't installed.
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const base = process.argv[2] ?? 'http://localhost:5173'
const out = process.argv[3] ?? '../docs/assets'
const only = process.env.ONLY?.split(',')
mkdirSync(out, { recursive: true })

const PASSWORD = 'GateSense@123'
const SHOTS = [
  { name: 'landing', role: null, path: '/', width: 1280, height: 900, fullPage: true },
  { name: 'landing-mobile', role: null, path: '/', width: 375, height: 812, fullPage: false },
  { name: 'login', role: null, path: '/login', width: 1280, height: 800 },
  { name: 'guard-console', role: 'guard', path: '/guard', width: 1440, height: 900 },
  {
    name: 'guard-console-hindi',
    role: 'guard',
    path: '/guard',
    width: 1440,
    height: 900,
    lang: 'hi',
  },
  { name: 'guard-console-mobile', role: 'guard', path: '/guard', width: 390, height: 844 },
  { name: 'resident-approvals', role: 'resident', path: '/resident', width: 390, height: 844 },
  { name: 'resident-passes', role: 'resident', path: '/resident/passes', width: 390, height: 844 },
  {
    name: 'resident-history',
    role: 'resident',
    path: '/resident/history',
    width: 390,
    height: 844,
  },
  {
    name: 'admin-overview',
    role: 'admin',
    path: '/admin',
    width: 1440,
    height: 1000,
    fullPage: true,
  },
  {
    name: 'admin-overview-dark',
    role: 'admin',
    path: '/admin',
    width: 1440,
    height: 1000,
    theme: 'dark',
  },
  { name: 'admin-vehicles', role: 'admin', path: '/admin/vehicles', width: 1440, height: 900 },
  { name: 'admin-watchlist', role: 'admin', path: '/admin/watchlist', width: 1440, height: 900 },
  { name: 'admin-audit', role: 'admin', path: '/admin/audit', width: 1440, height: 900 },
  { name: 'admin-settings', role: 'admin', path: '/admin/settings', width: 1440, height: 900 },
  { name: 'admin-tablet', role: 'admin', path: '/admin', width: 768, height: 1024 },
]
const EMAIL = {
  guard: 'guard@example.com',
  resident: 'resident@example.com',
  admin: 'admin@example.com',
}

async function tokensFor(role) {
  const response = await fetch(`${base}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: EMAIL[role], password: PASSWORD }),
  })
  if (!response.ok) throw new Error(`login as ${role} failed: ${response.status}`)
  const data = await response.json()
  return { access: data.access_token, refresh: data.refresh_token }
}

/** A few real admin changes, so the audit log screenshot has entries (local demo data only). */
async function prepareAuditLog() {
  const { access } = await tokensFor('admin')
  const call = (method, path, body) =>
    fetch(`${base}${path}`, {
      method,
      headers: { Authorization: `Bearer ${access}`, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    }).then((r) => r.json())
  await call('POST', '/api/v1/watchlist', {
    plate: 'UP14DX7788',
    reason: 'Unpaid parking dues since August; check with the office before letting in',
  })
  const vehicles = await call('GET', '/api/v1/vehicles?limit=1')
  if (vehicles.items?.[0])
    await call('PATCH', `/api/v1/vehicles/${vehicles.items[0].id}`, { colour: 'Pearl white' })
  await call('PATCH', '/api/v1/settings/visits', { cab_minutes: 15, visitor_parking_slots: 24 })
}
if (!only || only.includes('admin-audit')) await prepareAuditLog()

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL ?? 'chrome' })
for (const shot of SHOTS) {
  if (only && !only.includes(shot.name)) continue
  const context = await browser.newContext({
    viewport: { width: shot.width, height: shot.height },
    deviceScaleFactor: 2,
    reducedMotion: 'reduce',
  })
  const storage = {}
  if (shot.role) storage['gatesense.tokens'] = JSON.stringify(await tokensFor(shot.role))
  if (shot.lang) storage['gatesense.lang'] = shot.lang
  if (shot.theme) storage['gatesense.theme'] = shot.theme
  await context.addInitScript((entries) => {
    for (const [key, value] of Object.entries(entries)) localStorage.setItem(key, value)
  }, storage)
  const page = await context.newPage()
  await page.goto(base + shot.path, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: `${out}/${shot.name}.png`, fullPage: shot.fullPage ?? false })
  console.log(`saved ${shot.name}.png`)
  await context.close()
}
await browser.close()
