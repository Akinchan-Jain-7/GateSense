# ADR-0011: Escalation ladder, notifications and scheduled jobs

- **Status:** Accepted (pending owner review in the Phase 5 PR)
- **Date:** 2026-11-22

## Context

Overstaying visitors must be followed up in steps (email at the limit, a reminder after
30 minutes, a guard phone call after 60), each exactly once, even if a job runs twice, a
worker crashes mid-way, or the scheduler is down for an hour. Emails fail sometimes and
must be retried without being sent twice. Nightly checks and a privacy purge also need a
schedule.

## Decisions

1. **Celery Beat** puts jobs on the queue: escalation and email dispatch every minute,
   reconciliation at 03:00 IST, retention at 03:30 IST. Exactly one beat process runs;
   any number of workers execute.
2. **The ladder is a pure function of the clock:** `run_ladder(now)` looks at visit
   status and how far past `expected_exit_at` it is. Each step is idempotent on its own:
   the state machine refuses a second OVERSTAY/ESCALATE, emails have unique idempotency keys
   (`visit:<id>:overstay_reminder:resident:<user>`), and `escalation_tasks.visit_id` is
   unique. So running it twice, or once after an outage, does each due step exactly once
   and in order. Tests drive it with a mocked `now`.
3. **Queue, then dispatch.** Steps don't send email; they insert a `notifications` row with
   the rendered subject/text/HTML (`ON CONFLICT DO NOTHING` on the key). A dispatcher sends
   due rows, claiming them with `FOR UPDATE SKIP LOCKED` (two dispatchers never send the
   same row), retrying with exponential backoff (1, 2, 4 … 60 min) up to 5 attempts, then
   FAILED with the error kept for the admin.
4. **Exit closes escalation.** Any EXIT (camera or guard) resolves an open escalation task
   with outcome `vehicle_left`; a guard choosing `vehicle_left` also exits the visit.
5. **Visitor links are JWTs** with their own `type` (`visit_link`), expiring 2 hours after
   the time limit. They show only first name, flat, status and time remaining.
6. **Reconciliation flags** are stored rows, unique per (kind, subject), for the admin to
   resolve: exits without entries, entries followed by another entry with no exit, and
   visits still inside a day after the limit. A resident car with one open entry is normal
   (it's parked at home) and is never flagged.
7. **Retention deletes** visitors (once none of their visits is recent or open), redacts
   old notifications, anonymises ended guest passes, and deletes old snapshots. Visits and
   gate events stay for statistics, because they hold plates, not names.
8. **Safety net for Phase 4:** the every-minute job also times out overdue approvals whose
   Celery `eta` job was lost.

## Alternatives considered

- **Send emails directly inside the ladder.** Simpler, but a slow or failing SMTP server
  would hold the ladder up, and a crash between "sent" and "recorded" would resend.
- **A `stage` column on visits** instead of deriving steps from status + time + keys: an
  extra field to keep in sync; the derived approach can't drift.
- **Postgres cron (`pg_cron`) or OS cron**: not available on most free hosts; Celery Beat
  is already in the stack.
- **Deleting visits too in the purge**: loses the analytics (visit durations, busy hours)
  that hold no personal data. Rejected.

## Consequences

- Production must run three processes for the backend: API, worker, beat (`docker compose
  up` does).
- Email delivery depends on SMTP settings (Mailpit locally; a provider in Phase 8).
- Running two beat processes would double-schedule jobs. The jobs are idempotent, so
  nothing breaks, but it's wasteful and should be avoided.
