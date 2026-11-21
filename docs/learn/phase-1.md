# Phase 1 study guide: Backend core, database, auth

## What we built and why

The backend now has a real foundation: settings read from environment variables, JSON
logs, a PostgreSQL schema for the whole data model (created by an Alembic migration),
login with JWT access and refresh tokens, role checks (admin / guard / resident), API-key
login for cameras, and management APIs for flats, residents, vehicles, guards, gates,
devices and the watchlist, with paging, filters and an audit log. A seed script fills the
database with realistic demo data, and 146 tests run against a real Postgres. Every later
feature (gate events, approvals, escalations) builds on these tables and on "who is
calling and what may they do".

## Key concepts, explained simply

**Layers: router → service → model.** A *router* (`app/api/v1/*.py`) only handles HTTP:
read the input, call a service, return a response. A *service* (`app/services/*.py`) holds
the business rules and talks to the database. A *model* (`app/models/*.py`) describes a
table. Services never mention HTTP; they raise errors like `NotFoundError`, and one place
(`app/api/errors.py`) turns them into 404/409/422. So rules can be tested without a server
and reused by background jobs later.

**ORM and SQLAlchemy.** An ORM maps Python classes to tables: `Flat(block="B", number="402")`
becomes a row. We use SQLAlchemy's *async* API so a request waiting on the database doesn't
block other requests.

**Migration (Alembic).** A versioned script that changes the database schema
(`CREATE TABLE …`). The schema is never changed by hand: you change a model, run
`alembic revision --autogenerate`, review the script, and `alembic upgrade head` applies
it on every machine the same way. `alembic check` fails if models and migrations disagree
(a test runs it).

**Pydantic schemas.** Classes that describe the JSON going in and out. They validate
input (an email must look like an email, a phone must be a 10-digit Indian mobile) and
decide what is shown (the password hash is never in a response).

**Password hashing (Argon2id).** We never store passwords, only a *hash*: a one-way
scramble. At login we hash what was typed and compare. Argon2 is slow and memory-hungry on
purpose, so an attacker who steals the table can try only a few guesses per second.

**JWT (JSON Web Token).** A small signed text: `header.payload.signature`. The payload says
"user 123, access token, expires 10:15". The server signs it with a secret; if anyone edits
the payload the signature no longer matches. The server can check a JWT without looking
anything up, which is why it suits APIs.

**Access token vs refresh token.** The access token is short-lived (15 min) and sent on
every request; if stolen, it's useful only briefly. The refresh token lives 7 days and is
used only to get a new pair. We store refresh tokens and let each one work **once**
(rotation). If an already-used one shows up again, someone copied it, so we log that user
out everywhere (*reuse detection*).

**Authentication vs authorization.** Authentication = *who are you?* (login, token → 401
if it fails). Authorization = *are you allowed?* (role check → 403 if not).

**RBAC with dependencies.** FastAPI runs "dependencies" before a route. A route that takes
`admin: AdminUser` gets a dependency that loads the user from the token and checks the
role. A guard calling it gets 403 before the route body runs.

**API keys for devices.** Cameras can't type passwords, so each gets a long random key. We
store only its SHA-256 hash. A fast hash is fine here because the key is random (2²⁵⁶
possibilities); slow hashing only matters for guessable secrets like passwords.

**Pagination.** Lists return one page plus the total: `limit` = page size, `offset` = how
many to skip. Page 3 of 20 = `limit=20&offset=40`.

**Database constraints as the source of truth.** "Plate must be unique" lives in the
database (`UNIQUE`), not just in Python. If two requests race, the database still refuses
the second one; we catch that error and return a friendly 409.

**Test isolation with transactions.** Each test runs inside a database transaction that is
rolled back at the end, so tests never see each other's data and need no cleanup.

## Files to read, in order

1. `backend/app/main.py`: how the app is assembled (lifespan, middleware, routers, error handlers).
2. `backend/app/core/config.py`: every setting, its default, and the production safety check.
3. `backend/app/models/` (start with `society.py`, `user.py`, `vehicle.py`): tables as classes;
   notice `society_id`, `UniqueConstraint`, and `lazy="raise"`.
4. `docs/database.md`: the ER diagram and why each table exists.
5. `backend/alembic/versions/…_initial_schema.py`: the generated SQL steps; find the
   foreign key added *after* both tables exist.
6. `backend/app/core/security.py`: hashing, JWT create/decode (notice the pinned algorithm
   and the `type` claim), device keys.
7. `backend/app/services/auth.py`: login, refresh rotation and reuse detection.
8. `backend/app/api/deps.py`: `get_current_user`, `require_roles`, `AdminUser`, device auth.
9. `backend/app/services/vehicles.py` and `app/api/v1/vehicles.py`: one full resource; notice
   how thin the router is and how plates are normalised.
10. `backend/app/services/db_helpers.py`: `get_in_society` (404 for other societies) and
    `integrity_guard` (constraint error → 409).
11. `backend/app/seed.py`: how the demo data is generated deterministically.
12. `backend/tests/conftest.py`: the transaction-per-test setup.
13. `backend/tests/api/test_permissions.py`: every route × every role, plus a test that fails
    if a new route is added without being listed.
14. `docs/adr/0003-…` and `docs/adr/0004-…`: the decisions below, in full.

## Decisions made and alternatives rejected

| Decision | Rejected alternatives | Why |
|---|---|---|
| Async SQLAlchemy + psycopg 3 | Sync SQLAlchemy; asyncpg | psycopg 3 does sync *and* async, so API, migrations and Celery share one driver. |
| Argon2id | bcrypt, passlib | Current OWASP recommendation; passlib is unmaintained. |
| Refresh tokens stored and single-use | Stateless refresh tokens | Lets us log out, revoke and detect stolen tokens. |
| Load the user on every request | Trust the role inside the JWT | Deactivation and role changes take effect at once. |
| SHA-256 for device keys | Argon2 for device keys | Keys are random, so slow hashing adds cost but no safety. |
| UUID ids | Auto-increment integers | Not guessable in URLs; no leaking of record counts. |
| Enums as VARCHAR + CHECK | Native Postgres ENUM | Adding a value later is simple. |
| Vehicles belong to a flat | Vehicles belong to a person | Families share vehicles. |
| Tests on real Postgres | SQLite in memory | Same constraints and types as production. |
| Deactivate people, 409 on deleting things with history | Always hard delete; always soft delete | Keeps history correct without hiding records forever. |

## Likely interview questions

1. **How does login work end to end?** The client posts email + password. We find the user,
   verify the Argon2 hash, and return a 15-minute access JWT and a 7-day refresh JWT (whose
   id we store). The client sends the access token as `Bearer` on each request; when it
   expires, it swaps the refresh token for a new pair.
2. **Why both an access and a refresh token?** Short access tokens limit the damage of a
   leak; the refresh token avoids making users log in every 15 minutes, and because we
   store it we can revoke it.
3. **How do you revoke a JWT?** Access tokens can't be revoked individually; they just
   expire quickly. But we load the user each request, so a deactivated user is blocked at
   once. Refresh tokens are in the database and are revoked on logout or deactivation.
4. **What is refresh-token reuse detection?** Each refresh token works once. If a used one
   comes back, either the user or an attacker has a copy; we can't tell which, so we revoke
   all that user's sessions and both must log in again.
5. **How do you stop someone guessing which emails are registered?** Same error message for
   every login failure, and we run the slow hash check even when the email doesn't exist,
   so timing doesn't give it away.
6. **401 vs 403?** 401: we don't know who you are (missing or bad token). 403: we know who
   you are, and your role isn't allowed.
7. **How is role-based access implemented?** A dependency factory `require_roles(...)`
   produces a check; routes declare `AdminUser` or `StaffUser`. A parametrised test calls
   every route as every role and expects exactly the documented 403s.
8. **Why hash device API keys with SHA-256 but passwords with Argon2?** Passwords are
   human-chosen and guessable, so each guess must be expensive. A 256-bit random key can't
   be guessed, so a fast hash is enough and keeps each camera request cheap.
9. **How do your tests avoid leaking data between tests?** Each test wraps everything in one
   transaction on one connection; sessions commit only to savepoints; the transaction is
   rolled back at the end. Migrations run once per test run, so they're tested too.
10. **How do you prevent duplicate plates if two admins add the same car at once?** A
    `UNIQUE (society_id, plate_normalized)` constraint. The second insert fails in the
    database; we catch it in a savepoint and return 409.

## Exercise

Add a `GET /api/v1/flats/{flat_id}/vehicles` route that admins and guards may call and that
lists the flat's vehicles.

1. Which existing service function can you reuse? (Hint: look at the filters of
   `list_vehicles`.)
2. Which typed dependency gives "admin or guard"?
3. Add it, then run `uv run pytest tests/api/test_permissions.py`. Why does
   `test_every_api_route_is_covered` fail, and what do you add to make it pass?
4. Bonus: what should happen for a flat id from another society, and which helper gives you that?
