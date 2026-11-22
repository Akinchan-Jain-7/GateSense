import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end tests for the three critical journeys. They need the whole stack:
 * Postgres + Redis, the API with DEMO_MODE=true on :8000 (seeded with
 * `uv run python -m app.seed --reset`), and the web app. Locally that's `npm run dev`
 * (E2E_BASE_URL=http://localhost:5173); in CI the built app is served by `vite preview`.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // the journeys share one database
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        // Use the machine's Chrome when Playwright's own browser isn't installed.
        ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
      },
    },
  ],
})
