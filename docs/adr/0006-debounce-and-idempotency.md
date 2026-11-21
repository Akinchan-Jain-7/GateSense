# ADR-0006: Debounce strategy and idempotency for gate events

- **Status:** Accepted (pending owner review in the Phase 2 PR)
- **Date:** 2026-11-21

## Context

A camera sees a waiting car in dozens of video frames, and an unreliable network makes
devices retry uploads. The brief asks for "one plate in front of a camera = one event",
with a cooldown per plate per lane and an event hash for duplicates. Two different
problems hide in that sentence:

- **Exact duplicates:** the *same* read sent twice (a retry after a timeout).
- **Near duplicates:** *different* reads of the same car moments apart (more frames).

## Decision

1. **Idempotency in Postgres.** `event_hash = sha256(device id | cleaned plate text |
   capture time to the millisecond)` has a unique constraint. A retry finds the existing
   row and gets it back with `status: "duplicate"` (HTTP 200). If two copies race past the
   check, the unique constraint rejects the second insert, and we return the winner (and
   delete the loser's snapshot).
2. **Debounce in Redis**, keyed by lane (device) and *repaired* plate, so OCR jitter like
   `DLO1AB1234` vs `DL01AB1234` still counts as the same car. The value is
   "last seen time | id of the event that started the window".
3. **The window slides.** Every read pushes "last seen" forward. A car parked at the
   barrier for two minutes is one event; a new event starts only after the plate has been
   out of view for a full cooldown (`GATE_EVENT_COOLDOWN_SECONDS`, default 30).
4. **Capture time, not arrival time.** The comparison uses the camera's `captured_at`.
   When an offline camera (Phase 7) uploads an hour of buffered reads in seconds, two
   visits an hour apart stay two events. Capture times more than 5 minutes in the future
   are rejected, and times without a timezone are refused.
5. **Atomic check-and-set** with a small Lua script run inside Redis, so two simultaneous
   requests can't both decide they are first.
6. **Fail open.** If Redis is down, the read is accepted (logged as a warning). A duplicate
   event is better than a missed car, and exact retries are still caught by the hash.
7. A debounced read is **not stored**; the response (`status: "debounced"`, HTTP 200) returns
   the event it was folded into.

## Alternatives considered

- **Fixed window from the first read.** A car waiting 45 s would create two events. Rejected.
- **Window based on server arrival time** (a plain Redis key with a TTL). Simplest, but
  replayed offline reads would be merged wrongly. Rejected.
- **Debounce in Postgres** (look for a recent event of the same plate on the same lane).
  Works, but adds a query to every read on the hottest table, and has its own race.
  Redis is already in the stack for this kind of short-lived state.
- **Fuzzy debounce** (also fold reads one character apart). Would need a scan of recent
  plates per lane and loses atomicity. The ANPR worker (Phase 3) groups frames of one car
  before sending, which removes most of that noise at the source.
- **Storing debounced reads** with a flag. More data for analytics, but "one car = one
  event" is what every consumer (visits, pairing, analytics) wants. Rejected for v1.

## Consequences

- Correct behaviour depends on camera clocks being roughly right (NTP); the 5-minute
  future limit catches badly wrong clocks.
- When Redis is unavailable, a waiting car can create several events until it is back.
- The cooldown is a setting; Phase 7's load tests will show whether the Lua call costs
  anything measurable.
