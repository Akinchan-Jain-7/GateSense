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
   call `GET /api/v1/devices/me`, or send a plate read with `POST /api/v1/gate-events`.

## Endpoints

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
| `POST /gate-events` | – | – | – | **Device key only.** A camera reports a plate read (see below) |
| `GET /gate-events`, `GET /gate-events/{id}` | ✅ | ✅ | ❌ | Newest first. Filters: `direction`, `match_result`, `needs_review`, `gate_id`, `q`, `since`, `until` |
| `GET /gate-events/{id}/snapshot` | ✅ | ✅ | ❌ | The plate image (JPEG / PNG / WebP) |
| `GET /gate-events/review-queue` | ✅ | ✅ | ❌ | Unsure, unreadable or ambiguous reads not yet handled, newest first |
| `POST /gate-events/{id}/review` | ✅ | ✅ | ❌ | `{"action": "correct", "plate": "…"}` re-runs matching; `{"action": "dismiss"}`. Once per event (else 409) |
| `GET /alerts` | ✅ | ✅ | ❌ | Watchlist alerts, newest first. Filter: `acknowledged` |
| `POST /alerts/{id}/acknowledge` | ✅ | ✅ | ❌ | Safe to repeat; keeps the first guard and time |
| `POST /visits` | ✅ | ✅ | ❌ | Register a visitor → approval request (`gate_event_id` links the waiting car) |
| `GET /visits`, `GET /visits/{id}` | ✅ | ✅ | own flats | Filters: `status`, `inside`, `flat_id`, `q`. Phones are masked |
| `POST /visits/{id}/decision` | ✅ | ✅ | ❌ | Guard fallback after the timeout (409 while residents can still answer) |
| `POST /visits/{id}/enter`, `/exit` | ✅ | ✅ | ❌ | Manual entry / exit |
| `GET /approvals` | ✅ | ✅ | own flats | `status=pending` for the resident inbox |
| `POST /approvals/{id}/decision` | ❌ | ❌ | ✅ | `{"decision": "approve" \| "deny"}`; same answer twice = 200, different = 409 |
| `POST /guest-passes` | ❌ | ❌ | ✅ | Plate and/or one-time code (returned once) |
| `GET /guest-passes` | ✅ | ✅ | own flats | `active=true` = usable now |
| `POST /guest-passes/{id}/revoke` | ❌ | ❌ | ✅ | |
| `POST /guest-passes/redeem` | ✅ | ✅ | ❌ | Guard types a guest's code → visit inside |
| `GET /settings/visits` | ✅ | ✅ | ❌ | Time limits per category, approval timeout |
| `PATCH /settings/visits` | ✅ | ❌ | ❌ | Audited |
| `POST /telegram/link-code`, `DELETE /telegram/link` | ❌ | ❌ | ✅ | See [telegram.md](telegram.md) |
| `WS /ws?token=<access token>` | ✅ | ✅ | ✅ | Live events (below) |
| `GET /escalations` | ✅ | ✅ | ❌ | "Call the resident" tasks; `status=open` |
| `POST /escalations/{id}/resolve` | ✅ | ✅ | ❌ | `{"outcome": "reached" \| "not_reached" \| "vehicle_left", "notes": "…"}` |
| `GET /reconciliation`, `POST /reconciliation/{id}/resolve` | ✅ | ❌ | ❌ | Nightly findings; `resolved=false` |
| `GET /notifications` | ✅ | ❌ | ❌ | Email/Telegram log with delivery status |
| `GET /public/visits/{token}` | – | – | – | **No login**: the visitor's signed link (also `/visit/{token}` as a page) |
| `GET /health` | – | – | – | Public liveness probe |
| `GET /ready` | – | – | – | Public readiness probe (checks Postgres and Redis) |

Residents managing their own vehicles, guest passes, approvals and visitor registration
arrive in Phase 4.
Every admin create / update / delete is written to `audit_logs`.

## Sending a gate event (cameras)

`POST /api/v1/gate-events` takes `multipart/form-data` and the device key in `X-Device-Key`:

| Field | Required | Notes |
|---|:-:|---|
| `plate_text` | ✅ | What OCR read, 1–32 characters. Spaces, dashes and look-alike characters are fixed by the server |
| `confidence` | ✅ | OCR confidence, `0`–`1`. Below `PLATE_CONFIDENCE_THRESHOLD` (0.80) → review queue |
| `captured_at` | | When the camera saw it, ISO 8601 **with a timezone** (default: now). More than 5 min in the future → 422 |
| `direction` | | Optional check; must match the device's lane (`entry` / `exit`) |
| `snapshot` | | JPEG, PNG or WebP, up to `SNAPSHOT_MAX_BYTES` (2 MB, else 413) |

```bash
curl -X POST http://localhost:8000/api/v1/gate-events \
  -H "X-Device-Key: gsd_…" \
  -F plate_text="DL 01 AB I234" -F confidence=0.93 \
  -F captured_at=2026-11-21T09:30:00+05:30 \
  -F snapshot=@car.jpg
```

The response says what happened:

| `status` | HTTP | Meaning |
|---|---|---|
| `created` | 201 | A new event; `event.match_result` is `resident`, `visitor`, `watchlist`, `low_confidence` or `unknown` |
| `duplicate` | 200 | This exact read (same device, text and capture time) was already received: safe retry |
| `debounced` | 200 | The same plate was seen on this lane within the cooldown (30 s, sliding); `event` is the earlier one |

The rules behind it (matching order, visits, resident pairing, debounce) are explained in
[docs/learn/phase-2.md](learn/phase-2.md) and ADRs 0005–0008.

## Live updates (WebSocket)

Connect to `ws://localhost:8000/api/v1/ws?token=<access token>`. A bad token closes the
socket with code **4401**. The first message is `{"type": "hello", "data": {"role": …}}`;
send `ping` to get `{"type": "pong"}`. Every event looks like
`{"type": "...", "at": "<ISO time>", "data": {...}}`:

| Type | Sent to | `data` |
|---|---|---|
| `gate_event.created` | guards, admins | the gate event |
| `alert.created` | guards, admins | the alert (watchlist) |
| `approval.requested` | guards, admins, the flat's residents | the approval with its visit |
| `approval.decided` / `approval.timed_out` | same | the approval with its visit |
| `visit.updated` | guards, admins, the flat's residents | the visit |
| `escalation.created` / `escalation.resolved` | guards, admins | the escalation task with its visit |

