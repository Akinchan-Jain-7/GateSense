# ADR-0012: Frontend architecture and design system

- **Status:** Accepted
- **Date:** 2026-11-22
- **Phase:** 6

## Context

The web app serves three very different people: a guard on a night shift at a tablet, a
resident on a phone, and a society secretary at a laptop. It has to stay live (approvals
have a 3-minute window), work in Hindi for guards, install as an app for residents, and
look like a real product. The owner must be able to explain every part of it.

## Decisions

1. **One React app, three areas, lazy-loaded.** `/guard`, `/resident` and `/admin` are
   separate bundles behind role-checked routes, so a resident's phone never downloads the
   admin charts. One codebase keeps the design system and API client shared.
2. **Types generated from the backend's OpenAPI schema** (`openapi-typescript` +
   `openapi-fetch`). A renamed field breaks `tsc`, not the page. CI regenerates the types
   and fails on drift.
3. **TanStack Query for all server data; no global store.** Server state is cached,
   refetched on focus, and invalidated by live messages. The little client state there is
   (theme, language, tokens) lives in small React contexts.
4. **One WebSocket per tab, used to invalidate queries.** A message like `approval.decided`
   marks the matching cached lists stale and they refetch, instead of every screen patching
   its own copy. Reconnect uses exponential backoff with full jitter (1 s → 30 s), and after
   a reconnect everything refetches, because missed messages are not replayed.
5. **Tokens in localStorage.** Simple, survives reloads and PWA restarts. The risk is XSS;
   mitigations are short-lived access tokens, rotating refresh tokens, React's escaping and
   (Phase 7) a strict Content-Security-Policy. httpOnly cookies were rejected for now: the
   API is bearer-token based and serves cameras and bots too.
6. **Tailwind v4 tokens + shadcn-style components on Radix.** Components are copied into
   `src/components/ui` (the shadcn approach) and built on Radix for accessible dialogs and
   tabs. Colours are CSS variables, so light and dark themes are one class switch.
7. **Design: calm neutral greys, one accent from the plate itself.** See
   [docs/design.md](../design.md). Every vehicle is shown as a miniature Indian HSRP plate;
   IBM Plex Sans has a Devanagari sibling, so Hindi looks native.
8. **Chart colours are validated, not eyeballed.** The two series colours passed a
   colour-blind separation and contrast check against both theme surfaces; every chart has
   a hover tooltip and a "View as table" fallback.
9. **Demo mode is a backend switch** (`DEMO_MODE`). It enables the public `GET /demo`
   (one-click logins) and the admin reset. A real deployment leaves it off, so data can't
   be wiped from the UI and no login hints are published.
10. **Demo data has a past and a present.** The seed adds 14 days of closed history and a
    small "right now" state written exactly as the services would (including the ladder's
    already-sent emails), so the scheduled jobs find nothing to repeat.

## Alternatives rejected

- **Three separate apps:** triple the build and design upkeep for no user benefit.
- **Redux / Zustand for server data:** duplicates what TanStack Query already does.
- **Pushing full objects over the WebSocket and patching caches:** more code per screen,
  and a missed message leaves a screen silently wrong. Invalidate-and-refetch self-heals.
- **A component library with its own look (MUI, Ant):** fights the brief's calm style and
  is harder to theme to one accent.

## Consequences

- Each live message costs a refetch of the affected list; fine at a society's scale.
- Generated types mean the frontend PR that follows a backend change must include the
  regenerated `schema.d.ts` (CI enforces it).
