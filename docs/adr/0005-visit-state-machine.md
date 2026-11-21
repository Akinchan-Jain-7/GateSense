# ADR-0005: A state machine for visits

- **Status:** Accepted (pending owner review in the Phase 2 PR)
- **Date:** 2026-11-21

## Context

A visit is touched by many actors: the guard registers it, the resident approves or denies
it (Phase 4), the entry and exit cameras move it, a timeout expires it, and the escalation
job marks it overstayed and escalated (Phase 5). If each of them just sets `visit.status`,
it is easy to end up with impossible histories: a denied visitor marked `inside`, an exited
visit escalated an hour later, or a visit "approved" twice.

## Decision

1. **The rules are one table** in `app/services/visit_state.py`:
   `(current status, trigger) → new status`. Seven triggers (`approve`, `deny`, `enter`,
   `overstay`, `escalate`, `exit`, `expire`) and ten legal moves. Anything not in the table
   raises `IllegalTransitionError` (HTTP 409) and changes nothing.
2. **The module is pure:** no database, clock or I/O. It receives the visit, the trigger and
   the time, and sets the fields that go with the move (`enter` sets `entered_at` and the
   deadline `expected_exit_at = entered_at + time limit` unless one was agreed; `exit` sets
   `exited_at`). Every one of the 56 (status, trigger) pairs is unit-tested.
3. **One writer:** `app/services/visits.transition_visit` is the only code that changes a
   visit's status in the database. It applies the rule and adds a `visit_status_changes`
   row (from, to, trigger, time, the user or gate event that caused it) in the same
   transaction, so the history can never disagree with the visit.
4. **Time comes from the event**, not from the server clock: a camera-triggered `enter`
   uses the read's `captured_at`. Replayed offline reads (Phase 7) get correct times.
5. Visits start in `pending_approval` (unknown visitor) or `approved` (e.g. a guest pass).
   `exited`, `denied` and `expired` are terminal.

## Alternatives considered

- **Setting `status` directly wherever needed.** Fewer lines today, but the rules end up
  spread across routers, the camera pipeline and Celery jobs. Rejected.
- **A state-machine library** (e.g. `transitions`). Adds a dependency and its own concepts
  (callbacks, model binding) for what is a ten-entry dictionary. Rejected.
- **Postgres triggers that reject bad updates.** Strong guarantee, but the rules move into
  SQL that is harder to test and explain. The single-writer rule plus tests is enough.
- **Event sourcing** (rebuild status from the history table). Powerful, but more than the
  project needs; we keep a current `status` column *and* an append-only history.

## Consequences

- New behaviour (e.g. Phase 4's guard fallback after the approval timeout) is a new row in
  the table plus a test, not a hunt through the code.
- The history table gives the admin's audit view and the "why is this visit escalated?"
  answer for free.
- Callers must handle `IllegalTransitionError` (the API turns it into a 409).
