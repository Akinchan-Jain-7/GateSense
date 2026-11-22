# Phase 6 study guide: the web app

## What we built and why

GateSense now has a face. One React app serves three people: the **guard** (a dark,
high-contrast console with big buttons and a Hindi toggle), the **resident** (a phone app
that installs like a real app, for approving visitors and creating guest passes) and the
**admin** (a dashboard with charts and tables for running the society). A landing page
explains the product and has one-click demo logins. Everything updates live over a
WebSocket, so when a resident taps Approve, the guard sees it within a second without
refreshing. The backend got the endpoints the screens needed: analytics, the audit log
list, demo mode, guard-visible resident contacts and an "inside now" counter.

## Key concepts, simply

**Single-page app (SPA).** The browser downloads the app once; after that, moving between
screens only fetches data (JSON), not whole pages. React Router decides which screen to
show for each URL.

**Code splitting.** The guard, resident and admin areas are separate JavaScript files
(`lazy(() => import(...))`). A resident's phone never downloads the admin charts.

**Server state vs client state.** Server state is data that lives in the database
(visits, approvals); client state lives only in the browser (dark mode, language).
TanStack Query manages server state: it caches each request under a *query key* like
`['visits', {inside: true}]`, shows cached data instantly and refetches in the background.

**Invalidation.** Telling TanStack Query "this cached data is out of date". When the
WebSocket says `approval.decided`, we invalidate every query starting with `approvals` and
`visits`; any screen showing them refetches automatically.

**WebSocket.** A connection that stays open so the server can push messages. Ours has
reconnect with **exponential backoff**: wait 1 s, then 2 s, 4 s ... up to 30 s, plus random
*jitter* so a hundred tablets that lost Wi-Fi don't all reconnect in the same millisecond.

**Optimistic update.** When a resident taps Approve, the card disappears *before* the
server answers. If the server says no, we put the card back and show the error. It makes
the app feel instant, and it's safe here because approving is easy to retry.

**Generated API types.** The backend publishes an OpenAPI description of every endpoint.
`openapi-typescript` turns it into TypeScript types, so `api.GET('/api/v1/visits')` knows
exactly which filters exist and what comes back. If the backend renames a field, the
frontend stops compiling. CI regenerates the types and fails if they drift.

**Design tokens.** Named values (`--surface`, `--accent`, `--muted`) instead of raw
colours. The dark theme just swaps the values; components never change.

**PWA (progressive web app).** A website with a manifest (name, icon, start page) and a
service worker (caches the app's files). Phones offer "Add to home screen" and it opens
full-screen like a native app.

**i18n.** Every guard-console text comes from a dictionary (`i18n/en.ts`, `i18n/hi.ts`)
looked up by key, like `t('waiting.admit')` → "Let in" / "अंदर जाने दें".

**Accessibility.** Labels connected to inputs, visible focus rings, keyboard-reachable
dialogs (Radix handles focus trapping), colour never the only signal (badges always have
words), and charts with a "View as table" fallback.

## Files to read, in order

1. `docs/design.md`: the design decisions: colours, type, the plate chip.
2. `frontend/src/styles.css`: the tokens for both themes.
3. `frontend/src/components/ui/plate.tsx`: the signature component; note `aria-label`.
4. `frontend/src/lib/api/client.ts`: the typed client, token refresh on 401, readable errors.
5. `frontend/src/lib/auth.tsx`: who is signed in, and `RequireRole` for routes.
6. `frontend/src/lib/live.tsx`: the shared WebSocket, `INVALIDATES`, reconnect logic.
7. `frontend/src/lib/queries.ts`: data hooks and `useAction` (mutation + toast).
8. `frontend/src/app/App.tsx`: routes, lazy areas, providers.
9. `frontend/src/features/guard/columns.tsx`: arrivals, decisions, alerts, inside list.
10. `frontend/src/features/resident/ApprovalsPage.tsx`: the optimistic approve.
11. `frontend/src/features/admin/ResourcePage.tsx`: one table component for six resources.
12. `frontend/src/features/admin/charts.tsx`: Recharts with tooltips and table views.
13. `backend/app/services/analytics.py`: each dashboard number is one grouped SQL query.
14. `backend/app/demo_history.py`: how demo data gets a believable past and present.
15. `frontend/e2e/journeys.spec.ts`: the three journeys, end to end.

## Decisions and the alternatives we rejected

See [ADR-0012](../adr/0012-frontend-architecture.md). In short:

- **One app with three lazy areas**, not three apps (less duplication).
- **TanStack Query instead of Redux**, because nearly all our state is server state.
- **Invalidate on live messages, don't patch caches**: a missed message can't leave a
  screen wrong for long.
- **Tokens in localStorage**, accepted with XSS mitigations; httpOnly cookies rejected for
  now because cameras and the Telegram bot also use bearer auth.
- **shadcn-style components on Radix**, not a styled library like MUI, to match the calm
  brief with one accent.
- **Guards get residents' full phone numbers on call tasks** (they must dial them), while
  every list elsewhere masks phones.

## Likely interview questions

1. **How does the guard console stay live?** One WebSocket per tab. The server publishes
   events to Redis; the API forwards them to connected browsers. Each message invalidates
   the matching cached queries, which refetch.
2. **What happens if the Wi-Fi drops?** The socket closes, the app shows "Reconnecting…",
   retries with exponential backoff and jitter, and refetches everything once back.
3. **Why generate types from OpenAPI?** One source of truth. Backend changes that break the
   frontend fail at compile time and in CI, not in front of a user.
4. **What's an optimistic update and when is it unsafe?** Updating the UI before the server
   confirms. Unsafe when the action can't be undone or fails often, like payments.
5. **Where are tokens stored, and what's the risk?** localStorage; XSS could read them.
   Mitigated by short-lived access tokens, rotating refresh tokens, escaping and a CSP.
6. **How did you make the charts accessible?** Colours validated for colour-blind
   separation and contrast, a legend, hover tooltips, and a table view of the same data.
7. **How does the Hindi toggle work?** react-i18next with an English and a Hindi dictionary;
   IBM Plex Sans Devanagari matches the Latin font, and the `lang` attribute changes.
8. **How do you test the frontend?** Vitest + Testing Library for components (with a fake
   `fetch`), and Playwright for three full journeys against the real backend in CI.
9. **How is the busiest-hours chart computed?** One SQL query grouping entry-lane reads by
   hour in IST (`timezone('Asia/Kolkata', captured_at)`), split into residents vs others.
10. **How do you keep demo data from triggering real jobs?** History is fully closed; the
    "right now" state records the ladder's emails as already sent, and a test checks the
    ladder and reconciliation find nothing to do.

## Exercise

Add a fifth stat tile to the admin overview: **"Busiest hour"**, showing the hour with the
most entries (e.g. "6 pm"). You only need `OverviewPage.tsx`: the data is already in
`busiest_hours`. Then add a Vitest test that renders the page with a fake API response and
checks the tile shows the right hour.
