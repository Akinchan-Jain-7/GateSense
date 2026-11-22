import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { EMAILS, PASSWORD, tokens } from './helpers.js'

/**
 * Automated WCAG 2.1 AA checks (axe-core) on every main screen, in light and dark themes
 * and at phone width for the resident app. Axe finds about half of all accessibility
 * problems (contrast, missing labels, bad ARIA, keyboard traps it can see); the rest needs
 * a person with a keyboard and a screen reader, see docs/design.md.
 */

type Role = keyof typeof EMAILS

// Check settled pages: with animations on, axe can measure a row while it is still fading
// in and report low contrast that no one ever sees. The app honours this setting.
test.use({ contextOptions: { reducedMotion: 'reduce' } })

const SCREENS: { name: string; role: Role | null; path: string; ready: RegExp }[] = [
  { name: 'landing', role: null, path: '/', ready: /try the demo|demo/i },
  { name: 'login', role: null, path: '/login', ready: /sign in/i },
  { name: 'guard console', role: 'guard', path: '/guard', ready: /inside/i },
  { name: 'resident approvals', role: 'resident', path: '/resident', ready: /approv/i },
  { name: 'resident passes', role: 'resident', path: '/resident/passes', ready: /pass/i },
  {
    name: 'resident history',
    role: 'resident',
    path: '/resident/history',
    ready: /history|visit/i,
  },
  {
    name: 'resident profile',
    role: 'resident',
    path: '/resident/profile',
    ready: /profile|telegram/i,
  },
  { name: 'admin overview', role: 'admin', path: '/admin', ready: /overview|busiest/i },
  { name: 'admin visits', role: 'admin', path: '/admin/visits', ready: /visits/i },
  { name: 'admin flats', role: 'admin', path: '/admin/flats', ready: /flats/i },
  { name: 'admin residents', role: 'admin', path: '/admin/residents', ready: /residents/i },
  { name: 'admin vehicles', role: 'admin', path: '/admin/vehicles', ready: /vehicles/i },
  { name: 'admin guards', role: 'admin', path: '/admin/guards', ready: /guards/i },
  { name: 'admin gates', role: 'admin', path: '/admin/gates', ready: /gates/i },
  { name: 'admin watchlist', role: 'admin', path: '/admin/watchlist', ready: /watchlist/i },
  { name: 'admin checks', role: 'admin', path: '/admin/checks', ready: /check/i },
  { name: 'admin audit log', role: 'admin', path: '/admin/audit', ready: /audit/i },
  { name: 'admin settings', role: 'admin', path: '/admin/settings', ready: /settings/i },
]

// One sign-in per role for the whole file: the API allows 10 logins a minute per account.
const signedIn = new Map<Role, string>()

async function open(page: Page, role: Role | null, path: string, theme: 'light' | 'dark') {
  let pair: string | null = null
  if (role) {
    pair = signedIn.get(role) ?? JSON.stringify(await tokens(page.request, role))
    signedIn.set(role, pair)
  }
  await page.addInitScript(
    ([value, chosen]) => {
      if (value) localStorage.setItem('gatesense.tokens', value)
      localStorage.setItem('gatesense.lang', 'en')
      localStorage.setItem('gatesense.theme', chosen)
    },
    [pair, theme] as const,
  )
  await page.goto(path)
}

async function violations(page: Page) {
  // Skeletons fade out once data arrives; check the settled page, not the loading state.
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, { timeout: 15_000 })
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  return results.violations.map((v) => ({
    rule: v.id,
    impact: v.impact,
    help: v.help,
    where: v.nodes.slice(0, 3).map((n) => n.target.join(' ')),
  }))
}

for (const theme of ['light', 'dark'] as const) {
  test.describe(`${theme} theme`, () => {
    for (const screen of SCREENS) {
      test(`${screen.name} has no WCAG 2.1 AA violations`, async ({ page }) => {
        await open(page, screen.role, screen.path, theme)
        await expect(page.getByText(screen.ready).first()).toBeVisible()
        expect(await violations(page)).toEqual([])
      })
    }
  })
}

test.describe('phone width (375 px)', () => {
  test.use({ viewport: { width: 375, height: 812 } })
  for (const screen of SCREENS.filter((s) => s.role === 'resident' || s.role === 'guard')) {
    test(`${screen.name} has no WCAG 2.1 AA violations`, async ({ page }) => {
      await open(page, screen.role, screen.path, 'light')
      await expect(page.getByText(screen.ready).first()).toBeVisible()
      expect(await violations(page)).toEqual([])
    })
  }
})

test('the login form works with the keyboard alone', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel(/email/i).focus()
  await page.keyboard.type(EMAILS.admin)
  await page.keyboard.press('Tab')
  await page.keyboard.type(PASSWORD)
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/admin/)
})
