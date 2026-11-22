# ADR-0013: Hardening, offline mode and observability

- **Status:** Accepted
- **Date:** 2026-11-22
- **Phase:** 7

## Context

Before going live, the system has to survive the things a real gate throws at it: an
internet link that drops, a password-guessing bot, a misbehaving camera, oversized
uploads, and an operator who needs to know what's happening without reading code.

## Decisions

1. **Offline buffer at the edge (SQLite).** The ANPR worker writes undeliverable reads to a
   SQLite file and replays them oldest-first; new reads queue behind old ones, so the
   server sees reads in capture order (entry before exit). Replays are safe because the
   server already stores each read once (ADR-0006). Permanent rejections (4xx) move to a
   `rejected` table instead of blocking the queue. SQLite rather than a file of JSON lines:
   atomic writes, survives power cuts (WAL + `synchronous=FULL`), no extra service.
2. **Rate limiting: fixed one-minute windows in Redis**, per client IP and per account
   for login, per key for cameras. One round trip (INCR + EXPIRE). Fails open if Redis is
   down, like the debounce. Chosen over a library (slowapi) to keep it explainable in 40
   lines and over token buckets because the 2x burst at a window edge doesn't matter here.
3. **Security headers on every response:** `nosniff`, `X-Frame-Options: DENY`,
   `Referrer-Policy: no-referrer`, a `default-src 'none'` CSP for API responses, HSTS in
   production. The visitor page sets its own CSP allowing exactly its inline style and
   script by SHA-256 hash (no `'unsafe-inline'`). `/docs` keeps no CSP so Swagger UI loads.
4. **CORS locked down:** only configured origins, only the methods and headers the app
   uses, no credentials (bearer tokens, not cookies).
5. **Body size limits in middleware:** 1 MiB by default, snapshot size + 64 KB for camera
   uploads; checked from `Content-Length` and counted while streaming, so a missing header
   doesn't bypass it.
6. **Plain ASGI middleware instead of `@app.middleware("http")`.** Starlette's
   `BaseHTTPMiddleware` adds a task and a response-stream copy per request; plain ASGI
   classes don't, and they compose (request context → security headers → CORS → size).
7. **Observability:** a request id per request (kept from a proxy's `X-Request-ID` if
   sane), returned in the response and attached to every log line via a `ContextVar`;
   Prometheus metrics at `/metrics` with route *templates* as labels (bounded cardinality),
   plus domain counters (gate events by outcome, rate-limit refusals, open WebSockets).
   `/metrics` needs a bearer token when `METRICS_TOKEN` is set. `prometheus-client` is a
   small new dependency, added because the brief asks for the Prometheus format.
8. **Performance: fix the measured bottleneck, not a guessed one.** See
   [docs/performance.md](../performance.md). The API was CPU-bound in one process, with
   most CPU in ORM work per statement; the matcher built an ORM object for every plausible
   plate on every read. Now it compares `(plate, id)` rows and loads only the winner.
   Device "last seen" is written once a minute instead of per read.

## Consequences

- Behind a reverse proxy, the client IP for rate limiting must come from the proxy:
  uvicorn needs `--proxy-headers --forwarded-allow-ips=<proxy>` (Phase 8).
- Metrics are per process; with several workers, scrape each or use multiprocess mode.
- A fixed window allows up to twice the limit across a minute boundary. Acceptable.
