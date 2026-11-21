# ADR-0003: Database layer and data model refinements

- **Status:** Accepted (pending owner review in the Phase 1 PR)
- **Date:** 2026-11-21

## Context

`CLAUDE.md` §4 gives a starting data model and asks for refinements to be recorded. Phase 1
also has to pick how the API talks to Postgres: FastAPI is async, while the Celery workers
coming in Phase 5 are synchronous.

## Decision

### Database access

1. **SQLAlchemy 2.x async API with the psycopg 3 driver** (`postgresql+psycopg://…`).
   psycopg 3 supports both sync and async code with the same URL, so the API (async),
   Alembic migrations (sync) and future Celery tasks (sync) share one driver and one setting.
2. **Relationships use `lazy="raise"`.** Async code can't lazy-load. Forgetting to load a
   relationship raises a clear error instead of a confusing one deep inside SQLAlchemy.
3. **Services own transactions.** A request gets one session; the service calls `commit()`.
   Uniqueness and foreign-key rules are enforced by the database, and a small helper
   (`integrity_guard`) runs the write in a savepoint and turns the constraint error into a
   409 with a clear message. This also holds under concurrent requests, where a
   "check first, then insert" approach could race.

### Changes to the starting data model

| Change | Reason |
|---|---|
| UUID primary keys everywhere | Ids appear in URLs; sequential ids leak counts and are guessable. |
| Added **`refresh_tokens`** | Needed to make refresh tokens single-use and revocable (see ADR-0004). |
| A vehicle belongs to a **flat**, not a person | Families share cars; any resident of the flat can drive it. Avoids a second owner column. |
| `plate_normalized` unique **per society** (not globally) | Keeps multi-society tenancy possible. Lookups stay fast (indexed). |
| `residents` keeps `resident_type` (owner / tenant / family) and `is_primary_contact` | Approvals (Phase 4) need to know whom to ask first. |
| `devices.api_key_prefix` | The admin can tell keys apart without the full key ever being stored. |
| `gate_events` also stores `gate_id` and `direction` | Copied from the device at write time, so history survives a device being moved or renamed, and analytics don't need extra joins. |
| `visits.entry_event_id` / `exit_event_id` and `gate_events.visit_id` | Both directions are useful (event → visit for the live feed, visit → events for history). The circular foreign key is added after both tables exist. |
| `guest_passes`: `CHECK (plate OR code)` and `CHECK (use_count <= max_uses)` | The database refuses impossible passes, whatever the code does. |
| `notifications.idempotency_key` unique | A retried job can't send the same message twice (Phase 5). |
| Enums as `VARCHAR` + `CHECK`, values lower-case (`pending_approval`) | Easy to extend; lower-case matches JSON conventions. |
| All tables created now, including ones used from Phase 2 on | The whole model can be reviewed in one place. Later phases add columns in new migrations. |

### Delete rules

People are deactivated; flats, gates and devices can only be deleted while nothing refers
to them (409 otherwise); vehicles and watchlist entries are deleted outright. Details in
`docs/database.md`.

## Alternatives considered

- **Synchronous SQLAlchemy in FastAPI** (plain `def` routes in a thread pool). Simpler, but
  WebSockets and Redis pub/sub in Phase 4 are async anyway, and mixing styles in one app
  is harder to explain. Rejected.
- **asyncpg driver.** Fast, but async-only: Celery and Alembic would need a second driver.
  Rejected in favour of psycopg 3 for one driver everywhere.
- **SQLModel.** Fewer classes (one model for DB and API), but it couples the database shape
  to the API shape and lags behind SQLAlchemy and Pydantic releases. Rejected.
- **Native Postgres `ENUM` types.** Stricter, but adding a value needs `ALTER TYPE`, which is
  awkward in migrations. Rejected.
- **Integer ids.** Smaller indexes, but guessable in URLs. Rejected.

## Consequences

- One `DATABASE_URL` works for the API, migrations, tests and (later) workers.
- Tests run against real Postgres (not SQLite), so constraints and types behave exactly as
  in production. CI starts a Postgres service container for this.
- Every route must load the relationships its response needs (`joinedload`,
  `selectinload`), or the request fails loudly in tests.
