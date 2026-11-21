# ADR-0010: Approvals, real-time updates and background jobs

- **Status:** Accepted (pending owner review in the Phase 4 PR)
- **Date:** 2026-11-22

## Context

An unknown visitor waits at the barrier while a resident decides. The answer must reach the
guard within seconds, residents may answer on the web or Telegram (or both, or twice), and
if nobody answers in 3 minutes the guard decides. Several API processes and Celery workers
may run at once.

## Decisions

1. **One approval row per request, locked while deciding.** `decide_approval` loads the row
   `FOR UPDATE`, so two residents tapping at the same moment are serialised: the first wins,
   the second gets "already approved" (same answer, 200) or a 409 (different answer).
   Web and Telegram call the same function.
2. **Timeouts are checked twice.** A Celery task is scheduled for `expires_at` (`eta`), and
   any late answer also checks the clock itself. So a delayed or lost job can never let a
   resident decide after the deadline. The guard's `/decision` refuses while residents still
   have time.
3. **"The car is waiting" is data, not a guess.** When the guard registers a visitor against
   the unknown entry read (`gate_event_id`), the visit keeps that read as its entry event; on
   approval it moves straight to INSIDE. Without a linked read it stays APPROVED until a
   camera read or a manual "enter".
4. **Real time = Redis pub/sub → WebSocket.** Services publish JSON events
   (`gate_event.created`, `alert.created`, `approval.requested`, `approval.decided`,
   `approval.timed_out`, `visit.updated`) to `console:<society>` and `user:<id>` channels
   after committing; each WebSocket subscribes to its channels. Any process can publish and
   every connected client hears it. Publishing failures are logged, never fatal.
5. **WebSocket auth by access token in the query string** (browsers can't set headers on
   WebSockets). Bad or missing token → close code 4401. The socket releases its database
   connection right after authenticating.
6. **Jobs behind a `JobQueue` interface.** Routers ask for "approval timeout" / "notify
   approval"; production sends Celery tasks, tests record them. Tasks open their own engine
   with NullPool in a fresh event loop (`workers/runner.py`) and are idempotent.
7. **Guest-pass codes** are 8 characters from an alphabet without look-alikes, stored as an
   HMAC-SHA256 with the server secret; uses are counted with a conditional UPDATE.
8. **Telegram via webhook**, verified by the secret-token header; accounts linked with a
   one-time code kept hashed in Redis for 10 minutes; one `notifications` row per resident
   per approval prevents double sends.

## Alternatives considered

- **Polling** the API every few seconds instead of WebSockets: simpler, but slower and
  wasteful for a console that's open all night. Rejected.
- **Server-Sent Events**: one-way and a little simpler, but a WebSocket gives keep-alive
  ping/pong and room for client messages (e.g. acknowledging an alert) on one connection.
- **In-process timers** (`asyncio.sleep` then expire): lost on restart and duplicated across
  processes. Rejected for Celery `eta` + clock checks.
- **Telegram long polling** (`getUpdates`): no public URL needed, but needs an always-on
  extra process and doesn't fit serverless/free hosting. Webhook chosen; polling remains an
  option for local demos.
- **Plain SHA-256 for codes**: 8 characters from 31 symbols ≈ 8.5×10¹¹ combinations, which a
  stolen hash list could still be checked against offline. HMAC with a server secret stops that.

## Consequences

- The guard console and resident app (Phase 6) only need one WebSocket each.
- Redis is now on the approval path (pub/sub, Celery broker, link codes); its failure
  degrades to "refresh to see updates" plus the timeout double-check, not to lost data.
- A Celery worker must run for timeouts and Telegram (`docker compose up` starts one;
  natively: `celery -A app.workers.celery_app worker`, add `--pool=solo` on Windows).
