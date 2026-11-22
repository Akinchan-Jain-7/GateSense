/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// In development the API runs on :8000; the dev server forwards /api (including the
// WebSocket) so the browser sees one origin and no CORS setup is needed.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'GateSense',
        short_name: 'GateSense',
        description: 'Approve visitors and create guest passes for your flat.',
        start_url: '/resident',
        scope: '/',
        display: 'standalone',
        background_color: '#f7f8fa',
        theme_color: '#2147c9',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icon-512-maskable.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // The app shell works offline; API calls always go to the network (live data).
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/visit\//, /^\/docs/],
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        // Scripts the app never shows: browsers fetch them on demand if ever needed.
        globIgnores: ['**/*-cyrillic*', '**/*-greek*', '**/*-vietnamese*'],
      },
    }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Listen on all interfaces so the dev server is reachable from outside Docker.
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, ws: true, changeOrigin: true },
      '/visit': { target: apiTarget, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      '/api': { target: apiTarget, ws: true, changeOrigin: true },
      '/visit': { target: apiTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    // Node's Request needs absolute URLs (browsers resolve /api/... against the page).
    env: { VITE_API_URL: 'http://localhost' },
    include: ['tests/**/*.test.{ts,tsx}', 'src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**'],
      exclude: ['src/lib/api/schema.d.ts', 'src/main.tsx'],
      // CI fails below these (Phase 7). The Playwright journeys cover the rest end to end.
      // A few points under what the suite reaches (Nov 2026: 81% lines), so it can only go up.
      thresholds: { lines: 78, statements: 76, functions: 70, branches: 64 },
    },
  },
})
