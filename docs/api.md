# API reference

While the backend runs, the interactive docs at **http://localhost:8000/docs** are the
complete, always-current reference (generated from the code). This page explains the
conventions and who may call what. It grows with each phase and is finalised in Phase 9.

## Conventions

- **Base path:** `/api/v1` (probes `/health` and `/ready` sit at the root).
- **Auth for people:** `Authorization: Bearer <access_token>` from `POST /api/v1/auth/login`.
- **Auth for cameras:** `X-Device-Key: gsd_…` (the key returned when the device was created).
- **Lists** return a page: `{"items": [...], "total": 57, "limit": 20, "offset": 0}`.
  Query parameters `limit` (default 20, capped at 100) and `offset`, plus filters per resource.
- **Updates** are `PATCH` with only the fields to change. Sending `null` clears an optional
  field (e.g. `phone`); `null` for a required field is a 422.
- **Unknown fields are rejected** (422), so typos don't pass silently.
- **Errors** are `{"detail": "..."}` with these status codes:

| Code | Meaning |
|---|---|
| 401 | Not logged in, bad / expired token, or bad device key |
| 403 | Logged in, but your role may not do this |
| 404 | Doesn't exist (or belongs to another society) |
| 409 | Clashes with existing data: duplicate plate or email, or deleting something that has history |
| 422 | Invalid input: wrong format, invalid plate, missing field |
| 503 | `/ready` only: the database or Redis is down |

## Trying it in `/docs`

1. Seed demo data: `cd backend && uv run python -m app.seed`.
2. Open http://localhost:8000/docs, click **Authorize**, enter `admin@example.com` as the
   username and `GateSense@123` as the password (leave client id/secret empty).
3. Call any endpoint. Log out (**Authorize → Logout**) and log in as `guard@example.com` or
   `resident@example.com` to see the 403s.
4. For device auth, use **Authorize → X-Device-Key** with a key printed by the seed script and
   call `GET /api/v1/devices/me`.

## Endpoints (Phase 1)

| Method and path | Admin | Guard | Resident | Notes |
|---|:-:|:-:|:-:|---|
| `POST /auth/login` | – | – | – | Public. Form fields `username` (email), `password` |
| `POST /auth/refresh` | – | – | – | Public. `{"refresh_token": …}`; each refresh token works once |
| `POST /auth/logout` | – | – | – | Public. Revokes the refresh token |
| `GET /me` | ✅ | ✅ | ✅ | Your profile; residents also get their flats |
| `GET /flats`, `GET /flats/{id}` | ✅ | ✅ | ❌ | Filters: `block`, `q` (e.g. `402`, `B-402`) |
| `POST`, `PATCH`, `DELETE /flats…` | ✅ | ❌ | ❌ | Delete only if the flat has no residents / vehicles / history |
| `GET /vehicles`, `GET /vehicles/{id}` | ✅ | ✅ | ❌ | Filters: `flat_id`, `vehicle_type`, `is_active`, `q` (part of a plate) |
| `POST`, `PATCH`, `DELETE /vehicles…` | ✅ | ❌ | ❌ | Plate is cleaned and validated (`dl 01 ab 1234` → `DL01AB1234`) |
| `/residents` (all) | ✅ | ❌ | ❌ | Filters: `flat_id`, `block`, `resident_type`, `is_active`, `q`. Delete removes the flat link |
| `/guards` (all) | ✅ | ❌ | ❌ | Filters: `is_active`, `q`. Delete deactivates |
| `/gates` (all) | ✅ | ❌ | ❌ | Filter: `is_active`. Delete only without devices |
| `/devices` (all) | ✅ | ❌ | ❌ | Filters: `gate_id`, `direction`, `is_active`. Create and `POST /devices/{id}/rotate-key` return the key once |
| `GET /devices/me` | – | – | – | Device key only: lets a camera check its key |
| `/watchlist` (all) | ✅ | ❌ | ❌ | Filters: `is_active`, `q` |
| `GET /health` | – | – | – | Public liveness probe |
| `GET /ready` | – | – | – | Public readiness probe (checks Postgres and Redis) |

Residents managing their own vehicles, guest passes and approvals arrive in Phase 4.
Every admin create / update / delete is written to `audit_logs`.
