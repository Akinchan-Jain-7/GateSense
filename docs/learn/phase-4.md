# Phase 4 study guide: Visitors, approvals, guest passes, real time

## What we built and why

When an unknown car reaches the gate, the guard registers the driver (name, phone, flat,
purpose) against the camera's read. The flat's residents are asked to approve: instantly in
the web app (WebSocket) and on Telegram (Approve/Deny buttons). If nobody answers within
3 minutes (configurable per society), the request times out and the guard decides. Approval
admits the waiting car at once. Residents can also skip all of this with **guest passes**:
by plate (the entry camera lets the car in by itself) or by a one-time code the guard types.
Admins can change visit time limits and the approval timeout. Background work (timeouts,
Telegram messages) runs in a **Celery** worker, and everything the guard console needs is
pushed live over one WebSocket.

## Key concepts, explained simply

**WebSocket.** A connection that stays open so the server can push messages the moment
something happens, instead of the browser asking "anything new?" every few seconds.

**Pub/sub (publish/subscribe).** Senders publish a message to a named *channel*; everyone
subscribed to that channel gets it. Senders don't know who listens. We use Redis for it, so
a message published by any API process or worker reaches every connected browser.

**Background job / task queue.** Work that shouldn't block an HTTP request (or must happen
later) goes into a queue (Redis); a separate *worker* process (Celery) takes jobs out and
runs them. `eta` = "don't run before this time", which is how the 3-minute timeout works.

**Idempotency (again).** Doing it twice = doing it once. A resident tapping Approve twice,
or on web *and* Telegram, gets the same result; a Celery job that runs twice changes nothing
the second time; a Telegram message isn't sent twice (one `notifications` row per resident
per request, with a unique key).

**Row locking (`SELECT … FOR UPDATE`).** While one request decides an approval, the row is
locked; a second request waits, then sees it's already decided. That stops two residents
"both winning" with different answers.

**Defence in depth for deadlines.** The timeout job could be late or lost (broker down). So
every late answer also checks the clock itself and refuses. Two independent checks, one rule.

**Webhooks.** Instead of us asking Telegram for news, Telegram calls *our* URL when someone
presses a button. We check a secret header so nobody else can pretend to be Telegram.

**HMAC.** A keyed hash: `HMAC(secret, code)`. Without the server's secret you can't check
guesses against a leaked list of hashes, which matters for short codes like guest passes.

**Atomic conditional update.** `UPDATE guest_passes SET use_count = use_count + 1 WHERE … AND
use_count < max_uses RETURNING id` checks and increments in one step inside the database,
so two cars can't both use the last entry of a pass.

**Masking personal data.** Lists show `+91 98•••••210`: enough for a guard to recognise a
number, not enough to copy it.

## Files to read, in order

1. `backend/app/services/visitors.py`: the whole flow; read the module docstring first.
2. `backend/app/services/visits.py`: `start_visit` and `transition_visit`, the only writers.
3. `backend/app/services/guest_passes.py`: codes, HMAC, the atomic use count, `admit_with_pass`.
4. `backend/app/services/gate_events.py`, `_known_plates` and `apply_match`: where guest
   passes join camera matching, and `_publish`.
5. `backend/app/services/realtime.py` and `backend/app/api/v1/realtime.py`: publish and the socket.
6. `backend/app/services/telegram.py`: linking, buttons, webhook handling.
7. `backend/app/workers/` (`jobs.py`, `celery_app.py`, `runner.py`, `tasks.py`): how jobs run.
8. `backend/app/services/society_settings.py`: defaults vs saved settings.
9. `backend/tests/api/test_visitor_journey.py`: the whole path end to end, the best summary.
10. `docs/adr/0010-approvals-real-time-and-background-jobs.md` and `docs/telegram.md`.

## Decisions made and alternatives rejected

| Decision | Rejected | Why |
|---|---|---|
| WebSocket + Redis pub/sub | Polling; Server-Sent Events | Instant, one connection, works across processes |
| Celery task with `eta` + clock check on answers | In-process timers | Timers die with the process and run twice with two processes |
| Row lock while deciding | "Check then update" without a lock | Two residents could both win |
| Linked gate read → admit on approval | Wait for the camera to read the car again | The car is already at the barrier; debounce would hide a re-read |
| Token in WebSocket query string | Cookie auth | Browsers can't set headers on WebSockets; no cookie auth yet |
| Telegram webhook with secret header | Long polling | Fits free hosting; secret header proves the sender |
| HMAC for guest codes | Plain SHA-256 | Short codes are guessable offline from plain hashes |
| `JobQueue` interface | Calling Celery tasks from routers | Tests record jobs without a broker |

## Likely interview questions

1. **Walk me through an unknown visitor.** Camera read (unknown) → guard registers against
   that read → visit PENDING_APPROVAL + approval (3 min) → pushed by WebSocket and Telegram →
   resident approves → visit APPROVED then INSIDE (car admitted) → exit camera → EXITED.

2. **How do residents get notified instantly?** After committing, the API publishes a JSON
   event to Redis channels (`user:<id>`, `console:<society>`). Each WebSocket subscribes to
   its channels and forwards messages. Any process can publish; every client receives.

3. **What if two flatmates answer at the same time with different answers?** The approval
   row is locked (`FOR UPDATE`); the first commits, the second then sees it's decided and gets
   a 409. Same answer twice gets a 200.

4. **How does the 3-minute timeout work, and what if the worker is down?** A Celery task is
   scheduled with `eta = expires_at`. Independently, any answer after `expires_at` is refused
   and marks it timed out. The guard's endpoint also checks the clock.

5. **How do you secure the Telegram webhook?** Telegram sends a secret header we registered;
   we compare it in constant time. We also check the chat is linked to a resident of *that*
   flat, and button data is parsed strictly.

6. **How are guest-pass codes stored?** As HMAC-SHA256 with the server secret, shown once to
   the resident. The alphabet drops I/L/O/0/1 so guards don't mistype them.

7. **How do you stop a two-use pass being used three times?** One SQL statement increments
   only if `use_count < max_uses`; a CHECK constraint backs it up.

8. **Why a separate worker process?** Jobs survive API restarts, can run later (`eta`), retry,
   and don't slow down requests. Tasks are idempotent so retries are safe.

9. **How do you test WebSockets?** We drive the app's ASGI interface directly in the test's
   event loop, so the test database and Redis fixtures work, and publish real Redis messages.

10. **What would you add next?** Phase 5: the overstay escalation ladder and emails; later,
    rate limiting the redeem endpoint and push notifications for the PWA.

## Exercise

1. With the stack running and a worker started, set `approval_timeout_seconds` to 30 via
   `PATCH /api/v1/settings/visits` (admin), register a visitor (guard), and **don't answer**.
   Watch the worker log: when does `approvals.expire` run, and what does the approval's
   status become? Then approve as the guard with `POST /api/v1/visits/{id}/decision`.
2. In `test_guest_passes_and_settings.py`, add a test: a plate pass with `max_uses=2`, read
   by the camera 3 times (minutes apart). Before running, predict each `match_result`.
