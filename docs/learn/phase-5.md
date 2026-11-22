# Phase 5 study guide: Escalation, notifications, scheduled jobs

## What we built and why

Visitors who stay past their time limit are now followed up automatically, step by step.
At the limit the visit becomes OVERSTAYED and the visitor and residents get an email. After
30 minutes a reminder goes out. After 60 the visit becomes ESCALATED and a "call the
resident" task appears on the guard console, where the guard records the outcome. When the
exit camera sees the car, the visit and its task close. Every visitor who enters with an
email gets a welcome email with a signed link to a page that counts down their time.
**Celery Beat** runs these jobs on a schedule, alongside an email dispatcher with retries,
a nightly **reconciliation** that flags records that don't add up, and a daily **privacy
purge** of old visitor data. Every step is safe to repeat.

## Key concepts, explained simply

**Scheduler vs worker.** *Beat* is an alarm clock: every minute (or every night) it puts a
job on the queue. *Workers* take jobs off the queue and do them. Run one beat, many workers.

**Idempotent jobs.** A job may run twice (retries, overlaps, a crash after finishing but
before saying so). Ours check before acting: the state machine refuses a second "overstay",
each email has a unique key, a visit can have only one escalation task. Twice = once.

**Catching up.** The ladder doesn't remember "which step did I do last". It looks at the
clock and the visit: "60+ minutes over and not escalated → escalate". So after an hour of
downtime, one run does all the due steps, in order, once each.

**Mocking time.** Functions take `now` as a parameter instead of reading the clock inside.
Tests pass `limit + 30 minutes`, `limit + 60 minutes`… and check each step without waiting.

**Outbox pattern (queue, then send).** We first *write* the email to the `notifications`
table (in the same transaction as the status change), then a separate dispatcher sends it.
If sending fails, the row is still there to retry; if the app crashes, nothing is lost.

**Exponential backoff.** Retry after 1 min, then 2, 4, 8… (capped at 1 h), so a broken mail
server isn't hammered, then give up after 5 tries and keep the error for the admin.

**`FOR UPDATE SKIP LOCKED`.** "Lock the rows I'm about to send, and skip rows someone else
has locked." Two dispatchers can run at once and never send the same email twice.

**Signed links (JWT).** The email link contains the visit id and an expiry, signed with the
server's secret. Nobody can forge or edit it, it needs no login, and it stops working by itself.

**Data retention.** Personal data (names, phones, emails, photos) is deleted after 90 days.
Statistics (how long visits last, busy hours) stay, because they don't identify anyone.

## Files to read, in order

1. `backend/app/services/escalation.py`: the ladder (read the docstring), guard tasks, sweep.
2. `backend/tests/api/test_escalation.py`: the mocked-clock test of every step, the brief's "done when".
3. `backend/app/services/notifications.py`: queue, dispatcher, backoff, SMTP mailer.
4. `backend/app/services/emails.py`: text + HTML templates, escaping, Indian time.
5. `backend/app/services/visits.py`, `_welcome_visitor` and `_close_escalation`: the hooks.
6. `backend/app/services/visit_links.py` and `backend/app/api/public.py`: signed links and the page.
7. `backend/app/services/reconciliation.py`: the three checks and why parked cars aren't flagged.
8. `backend/app/services/retention.py`: what's deleted, what stays, and why.
9. `backend/app/workers/celery_app.py` (`beat_schedule`) and `tasks.py`: how it's scheduled.
10. `docs/adr/0011-escalation-notifications-and-scheduled-jobs.md`.

## Decisions made and alternatives rejected

| Decision | Rejected | Why |
|---|---|---|
| Derive the ladder step from status + clock + keys | A `stage` counter column | Can't drift out of sync; catches up after outages |
| Queue emails in the DB, send separately | Send inside the ladder | A slow or failing mail server can't block or duplicate steps |
| Backoff + max attempts + error kept | Retry forever / give up at once | Survives blips, stops on real problems, shows why |
| One escalation task per visit (unique) | Check-then-insert in code | The database guarantees it even under races |
| Nightly reconciliation as stored flags | Just log findings | The admin can work through and resolve them |
| Delete visitors, keep visits | Delete everything old | Privacy without losing anonymous statistics |

## Likely interview questions

1. **How do you make sure each escalation email is sent exactly once?** Each has a unique
   idempotency key; the queue insert is `ON CONFLICT DO NOTHING`; the dispatcher claims rows
   with `SKIP LOCKED` and marks them SENT. A rerun finds nothing new to do.

2. **What if the scheduler is down for an hour?** The ladder computes what's due from the
   clock, so the next run does notice, reminder and escalation in one go, once each.

3. **How did you test something that takes an hour?** Every function takes `now`; the test
   calls the ladder at limit −1, 0, +29, +30, +59, +60, +90 minutes and checks each step.

4. **Why not send the email immediately?** The outbox pattern: the message is saved with
   the status change in one transaction, then sent. A failure means a retry, not a lost or
   double email.

5. **How do retries work?** `attempts` and `next_attempt_at` on each row; delays 1, 2, 4…
   up to 60 minutes; after 5 attempts it's FAILED with the error, visible in the admin log.

6. **Two workers run the dispatcher at the same time: what happens?** `SELECT … FOR UPDATE
   SKIP LOCKED`: each takes different rows; nobody waits, nothing is sent twice.

7. **How does the visitor's countdown link work without a login?** A JWT with the visit id,
   type `visit_link` and an expiry, signed with the server secret. It can't be used as a
   login token because the type is checked.

8. **What does reconciliation look for, and why not flag every open entry?** Exits without
   entries, double entries without an exit, visitors still inside a day later. A resident's
   car with one open entry is just parked at home.

9. **What's deleted after 90 days?** Visitor names/phones/emails (once no recent or open
   visit), message contents and addresses, guest phone numbers, snapshots. Visit and gate
   records stay for statistics.

10. **What runs in production?** API, Celery worker(s), exactly one Celery Beat, plus
    Postgres, Redis, object storage and an SMTP provider.

## Exercise

1. In `test_escalation.py`, change the settings so the reminder is at +15 and escalation at
   +20 minutes (`monkeypatch.setattr(get_settings(), "overstay_reminder_minutes", 15)`) and
   write a test that ticks at 0, 15 and 20 minutes. Predict the `LadderResult` of each tick first.
2. Run the stack with `docker compose up`, register and approve a visitor with your own
   email address, mark them entered, and open Mailpit (http://localhost:8025). Click the
   link in the welcome email. What happens to the page when the time limit passes?
