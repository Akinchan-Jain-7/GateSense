# GateSense progress tracker

The build is split into phases (see `CLAUDE.md` §6). Each phase is one branch and one PR.
The agent updates this file at the start and end of every session.

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Repo foundation | ✅ Done | [#1](https://github.com/Akinchan-Jain-7/GateSense/pull/1) |
| 1 | Backend core, database, auth | ✅ Done | [#2](https://github.com/Akinchan-Jain-7/GateSense/pull/2) |
| 2 | Gate event engine | ✅ Done | [#4](https://github.com/Akinchan-Jain-7/GateSense/pull/4) |
| 3 | ANPR ML pipeline | ✅ Done (model accuracy pending owner Colab runs) | [#6](https://github.com/Akinchan-Jain-7/GateSense/pull/6) |
| 4 | Visitors, approvals, guest passes, real time | ✅ Done | [#7](https://github.com/Akinchan-Jain-7/GateSense/pull/7) |
| 5 | Escalation, notifications, scheduled jobs | ✅ Done | [#8](https://github.com/Akinchan-Jain-7/GateSense/pull/8) |
| 6 | Frontend (professional UI) | ✅ Done | [#9](https://github.com/Akinchan-Jain-7/GateSense/pull/9) |
| 7 | Hardening, offline mode, performance | ✅ Done | [#10](https://github.com/Akinchan-Jain-7/GateSense/pull/10) |
| — | Closing the gaps in Phases 0–7 | ✅ Merged (detector numbers pending the Kaggle run) | [#12](https://github.com/Akinchan-Jain-7/GateSense/pull/12) |
| 8 | Docker and deployment | 🟡 Mostly built (draft) | [#11](https://github.com/Akinchan-Jain-7/GateSense/pull/11) |
| 9 | Polish, docs, release | ⚪ Not started | |

**Now:** the detector results from Kaggle (follow-up PR), then the rest of Phase 8 and
Phase 9. Phase 8 goes live once the owner picks a host and creates the account (see
`docs/deployment.md`, "What the owner does").

**Waiting on the owner:** labelled photos for the OCR comparison (notebook 02), a Telegram
bot token for one real end-to-end test, and a first run of the app on their own machine.

## Standing rules from the owner

- Commits are authored by **Akinchan Jain**
  (`187171836+Akinchan-Jain-7@users.noreply.github.com`). Do **not** add Claude as an author
  or co-author, and add no "Generated with" footers to commits or PRs.
- **Dev workflow:** supporting services (Postgres, Redis, Mailpit, storage) run in Docker;
  backend and frontend run natively. Keep the CI `compose` job so the full Docker stack is
  checked on every PR. Production images are built in Phase 8. Setup instructions in each
  phase target this workflow (see `CONTRIBUTING.md`).
- The owner's local clone lives at `C:\Users\akinc\projects\GateSense` (not in OneDrive).
- **One phase per chat, agent merges (owner, 2026-11-21).** Each phase is built in its own
  new chat, working in the owner's project folder. The agent builds the phase, opens the PR,
  merges it itself once CI is green, then ends with a phase summary and asks the owner
  whether to proceed. The owner studies the code after the build, not during it. Anything
  only the owner can do (Colab GPU runs, hosting accounts, secrets) is prepared and listed
  in the summary.

## Phase 8: Docker and deployment

Branch: `phase-8-deployment`

- [x] Demo traffic simulator (`simulator/`): residents, visitors with approvals, guest passes,
      blurry reads, watchlist hits and overstays, all through the public API; restarts by
      itself after a demo reset. Tests against a fake API, plus a 5-minute run against the
      real local stack
- [x] Nightly demo reset (Celery Beat, 04:00 IST, only when `DEMO_MODE=true`)
- [x] Production Dockerfiles: backend `prod` target (slim, non-root, healthcheck; one image
      for API, worker and beat), frontend `prod` target (Caddy: static build, automatic HTTPS,
      strict CSP, `/api` forwarded), simulator image (non-root)
- [x] `docker-compose.prod.yml` + `.env.prod.example`: only Caddy is published; one-shot
      `migrate` step; simulator behind the `demo` profile
- [x] `python -m app.setup_society`: first admin for a real (non-demo) society
- [x] CI: simulator job; `compose-prod` job builds the prod images and checks the running
      stack through Caddy
- [x] `deploy.yml`: after green CI on `main`, multi-arch (amd64 + arm64) images to GHCR,
      then an SSH deploy once the server secrets exist
- [x] Free-tier check and hosting proposal (`docs/deployment.md`), ADR-0014 (proposed)
- [x] `docs/learn/phase-8.md`
- [ ] **Owner:** choose a host, create the account and server, add the GitHub secrets
- [ ] Live URL works, demo logins work, dashboard shows simulated traffic (after the owner's step)

### Notes and deviations

- **One server instead of several free platforms.** The brief suggested Render / Railway /
  Fly.io + Neon + Upstash. Checked in November 2026, none of those free tiers can run an
  always-on Celery worker, Beat and the simulator together (details and sources in
  `docs/deployment.md`). The proposal is one small VM running `docker-compose.prod.yml`.
  ADR-0014 stays **Proposed** until the owner agrees.
- **Caddy serves the frontend** instead of Vercel, so the app, the API and the WebSocket share
  one origin and one certificate (no CORS, no second deploy). Vercel stays an option.
- **Docker images couldn't be pulled in the agent's workspace** (registries blocked), so the
  production images were built and tested by the `compose-prod` CI job on GitHub's runners.
- **Simulator speed:** `SIM_SPEED` compresses only the simulator's own clock. The server's
  timers (approval timeout, visit limits) run in real time, so the live demo uses speed 1.

## Closing the gaps in Phases 0–7

Branch: `gaps-phase-0-7`. The owner asked for every known gap in Phases 0–7 to be closed
before Phase 8 and 9 continue.

- [x] **Plate detector training moved to Kaggle** (owner's account, run by the agent in the
      owner's browser). Notebook 01 now runs on Kaggle or Colab and needs no API key: four
      CC0 Kaggle datasets for training, an Apache 2.0 set from a different source as the
      test set, exact duplicates and pre-cropped plates removed. The dataset builder was
      tested locally on fake data shaped like each source
- [ ] Kaggle run finished; real detector numbers in `anpr/eval/results/`, README, ADR-0009
- [ ] CPU latency of the trained model (`eval/benchmark_detector.py`), model on a
      `models-v1` release
- [x] **Accessibility:** axe-core WCAG 2.1 AA checks on 18 screens in both themes, phone
      width and keyboard-only login (42 checks, in CI). Fixed what it found: `faint` text
      below 4.5:1, the guard language button's spoken name, a range picker built from tabs
      without panels; confirm dialogs are now `alertdialog`
- [x] **Frontend tests:** 36 → 53 tests, line coverage 63% → 81% (admin pages, live
      connection, guest codes, Telegram linking); CI threshold 55% → 78%
- [x] **Telegram through the notification outbox** (the Phase 5 follow-up): queued like
      email, delivered at once, retried with backoff, cancelled when the approval was
      answered meanwhile. Migration adds `notifications.payload` and the `cancelled` status
- [x] **Load test with two API workers:** no gain on the 2-vCPU machine (172.5 vs 169.7
      req/s, 0 failures), explained in `docs/performance.md`
- [ ] Owner: labelled photos → notebook 02 (OCR comparison); Telegram bot token → one real
      Telegram test; run the app locally once
- [x] Docs, PR, merge ([#12](https://github.com/Akinchan-Jain-7/GateSense/pull/12))

### Notes and deviations

- **Data with a clear licence only.** The largest Indian plate set on Kaggle (15k images)
  has no stated licence and mixes augmented copies into its test split, so it was not used.
  The chosen sets are smaller (~700 usable images) but CC0 / Apache 2.0, and the test set
  is a different source, so the score isn't inflated by near-copies. Of one CC0 set's 2,083
  images, ~1,900 are already-cropped plates (no use for a detector) and are filtered out.
- **Kaggle run notes:** a background run can't attach new datasets, so all five were added
  as notebook inputs first (version 1 failed on exactly that). The GPU queue was long.

## Phase 7: Hardening, offline mode, performance

Branch: `phase-7-hardening`

- [x] ANPR offline buffer (SQLite, WAL): ordered replay, new reads queue behind old ones,
      backoff 5 s → 5 min, permanent rejections set aside, survives restarts; Docker volume
- [x] Server-side dedup already in place (event hash); replays are safe
- [x] Rate limits (Redis fixed window, fails open): login per IP and per account, cameras
      per key; 429 + Retry-After
- [x] Security headers on every response, strict CSP for API JSON, hashed CSP for the
      visitor page, HSTS in production; CORS narrowed to used methods/headers
- [x] Body size limits (1 MiB; snapshot + 64 KB for uploads), checked while streaming too
- [x] Request ids (kept from proxies if sane) on every log line; Prometheus `/metrics`
      (route templates, gate events, rate limits, open WebSockets), optional bearer token
- [x] Plain ASGI middleware replaces BaseHTTPMiddleware
- [x] Locust load test + repeatable benchmark; bottleneck found by measurement (CPU-bound,
      ORM objects for every plate per read), fixed: 114.5 → 149.4 req/s (80 vehicles),
      61.9 → 98.0 (500 vehicles); final build 159.1 req/s, p95 410 ms
- [x] Load test found a pairing race (500): fixed with a row lock + a two-connection test
- [x] Coverage thresholds in CI: backend 90 (now 96), ANPR 80 (now 87), frontend 55 lines
      (now 63, up from 29)
- [x] `docs/performance.md`, ADR-0013, `docs/learn/phase-7.md`, api.md, anpr README

Notes for Phase 8: run uvicorn with `--proxy-headers --forwarded-allow-ips` behind the
host's proxy (rate limits need the real client IP); set `METRICS_TOKEN`; add the web
app's CSP in its static server.

## Phase 6: Frontend (professional UI)

Branch: `phase-6-frontend`

- [x] Design system: tokens (light + dark), IBM Plex Sans + Devanagari, HSRP plate chip,
      shadcn-style components on Radix ([docs/design.md](design.md))
- [x] Typed API client generated from OpenAPI, token refresh, readable errors; CI drift check
- [x] One shared WebSocket: reconnect with backoff + jitter, query invalidation, catch-up
- [x] Landing page with one-click demo logins and an architecture diagram; sign-in page
- [x] Guard console: arrivals with snapshots and plate review, decisions with countdowns,
      watchlist alerts, call tasks with tap-to-call, inside list, EN / हिन्दी, dark default
- [x] Resident PWA: approvals (optimistic), guest passes (plate or code), history, Telegram
- [x] Admin: analytics overview (validated chart palette, table views), flats, residents,
      vehicles, guards, gates and cameras, watchlist, visits, audit log, gate checks,
      settings, demo reset
- [x] Backend: analytics overview + inside-now, audit-log list, demo mode (info + reset),
      confidence threshold and visitor parking as admin settings, resident contacts on
      call tasks, 14 days of demo history plus a live "right now" state
- [x] Tests: Vitest (28), Playwright journeys (resident entry, visitor approval, overstay
      call task) in a new CI job; backend 479 tests (96% coverage)
- [x] Screenshots in `docs/assets/`, ADR-0012, `docs/learn/phase-6.md`, api.md

Notes for later phases: the live demo needs the traffic simulator (Phase 8) to keep the
console busy; a demo reset regenerates camera keys, so the cloud simulator must fetch a key
after each reset (Phase 8).

## Phase 5: Escalation, notifications, scheduled jobs

Branch: `phase-5-escalation-notifications`

- [x] Celery Beat schedule: escalation + email dispatch every minute, approval sweep,
      nightly reconciliation (03:00 IST), daily retention purge (03:30 IST); `beat` in Compose
- [x] Escalation ladder: limit → OVERSTAYED + emails; +30 min reminder; +60 min ESCALATED +
      guard call task; each step exactly once, catches up after downtime
- [x] Escalation tasks: list, resolve with outcome (reached / not reached / vehicle left);
      any exit closes the open task
- [x] Email templates (plain text + HTML, escaped, Indian time) over SMTP (Mailpit in dev)
- [x] Notification log with rendered messages, idempotency keys, `SKIP LOCKED` dispatcher,
      exponential backoff, max attempts; admin log endpoint
- [x] Welcome email with a signed, expiring visitor link + public countdown page
- [x] Nightly reconciliation flags (exit without entry, entry never closed, visit not closed)
- [x] Retention purge: visitors, message contents, guest phones, snapshots (per-society days)
- [x] Time-mocked tests: an overstaying visit goes through every step exactly once
- [x] Verified live: real Celery worker + Beat + local SMTP server: a 61-minute-overdue visit
      → OVERSTAYED → ESCALATED (one task), 4 emails queued and delivered over SMTP
- [x] ADR-0011, `docs/learn/phase-5.md`, api.md, database.md, .env.example

### Notes and deviations

- New table `reconciliation_flags`; `notifications` gained `subject`, `body_text`, `body_html`,
  `next_attempt_at`; `escalation_tasks.visit_id` is now unique; `society_settings` gained
  `visitor_retention_days`.
- Telegram approval messages (Phase 4) kept their own idempotent sending here; they moved
  onto the same outbox later (see "Closing the gaps in Phases 0–7").
- The visitor page is server-rendered HTML for now; the React app may restyle it in Phase 6.

## Phase 4: Visitors, approvals, guest passes, real time

Branch: `phase-4-visitors-approvals-realtime`

- [x] Visitor registration (guard): visitor found or created by phone, visit
      PENDING_APPROVAL, approval with the society's timeout; link the waiting car's read
- [x] Resident decisions (web): row-locked, idempotent, other flats get 404; late answers
      refused by a clock check; approval admits a linked waiting car (→ INSIDE)
- [x] Timeout (Celery task with `eta`) → guard fallback `POST /visits/{id}/decision`;
      flats with no residents go straight to the guard; manual enter/exit
- [x] Guest passes: plate (auto-admitted by the entry camera) or code (HMAC, look-alike-free
      alphabet), validity window, atomic usage limit, revoke, guard redeem
- [x] Visit categories with admin-configurable limits + approval timeout (`society_settings`),
      service visits with a resident-set duration; audited
- [x] Telegram bot: one-time link codes, inline Approve/Deny, webhook secret check,
      idempotent notification log; `docs/telegram.md`
- [x] WebSocket `/api/v1/ws` over Redis pub/sub: console feed for staff, personal channel
      for everyone; gate events, alerts, approvals, visits published
- [x] Celery app + worker in Compose; jobs behind a `JobQueue` interface
- [x] Integration test of the full unknown-visitor path (camera → registration → WebSocket +
      Telegram → approve → admitted → exit camera), plus the timeout path
- [x] Verified live: API + real Celery worker, 30 s timeout → job ran at `eta`, approval timed out
- [x] ADR-0010, `docs/learn/phase-4.md`, api.md (endpoints + WebSocket events), database.md
- [ ] **Owner (optional, any time):** create the Telegram bot with BotFather and put the token
      in `.env` (steps in `docs/telegram.md`); the webhook is registered after deployment (Phase 8)

### Notes and deviations

- New table `society_settings`, columns `users.telegram_chat_id` and `visits.duration_minutes`.
- New dependencies: `celery[redis]` (in the brief's stack) and `httpx` (Telegram client).
- The WebSocket takes the access token in the query string (browsers can't send headers);
  request logs record paths only.
- A periodic sweep of overdue approvals (in case the broker loses a timeout job) arrives with
  Celery Beat in Phase 5; until then the clock check on every answer covers it.

## Phase 3: ANPR ML pipeline

Branch: `phase-3-anpr-pipeline`

- [x] `anpr` package: detector (YOLOv8 → ONNX Runtime, NumPy letterbox/decode/NMS) → crop →
      OCR (EasyOCR / PaddleOCR behind one interface) → clean → frame tracker with voting → client
- [x] Sources: webcam index, RTSP/HTTP, video file (video-time timestamps), image folder,
      `--simulate`; `--dry-run`
- [x] Client: multipart POST with device key; retries with backoff on network errors, 429, 5xx
- [x] Model download from GitHub Releases with SHA-256 check (weights never in git)
- [x] Colab notebook 01: Roboflow (key from Colab Secrets) or Drive dataset → one-class
      remap → train YOLOv8n and YOLOv8s → score on test split → ONNX → pick by a fixed rule.
      Its dataset/train/score/export cells were dry-run on the build machine (1 epoch, tiny data)
- [x] Colab notebook 02: EasyOCR vs PaddleOCR on labelled photos, per condition, fixed rule
- [x] Dataset guide for the owner's photos: `anpr/DATASET.md`
- [x] Evaluation scripts → `anpr/eval/results/`; **measured** CPU latency (FP32 vs INT8
      dynamic vs INT8 static) for the YOLOv8n/s plate architectures
- [x] End-to-end run: synthetic gate video → stand-in detector → real EasyOCR → tracker →
      real API: 4 cars → 4 correct events (found and fixed a plate-repair bug)
- [x] ADR-0009, `docs/learn/phase-3.md`, anpr README, Dockerfile, CI job (tests + image)
- [ ] **Owner:** run notebook 01 in Colab (needs a free Roboflow key in Colab Secrets), upload
      `plate_detector.onnx` to a `models-v1` release, share `detector_comparison.md/.json`
- [ ] **Owner:** label ~50+ photos per condition (`anpr/DATASET.md`), run notebook 02, share
      `ocr_comparison.md`; then the README accuracy rows and ADR-0009's choice get filled in

### Notes and deviations

- Datasets (Roboflow, Kaggle, Hugging Face) and the PyTorch CPU index are blocked from the
  build machine, so training and accuracy evaluation move to the owner's Colab runs, as the
  brief allows. PyTorch from PyPI *did* install, which made the latency benchmark and the
  notebook dry-run possible.
- The "video run produces correct gate events" check used a **stand-in detector** (fixed
  box) because no trained model exists yet. OCR, tracker, client and API were all real.
- Latency numbers are from the 2-core cloud build machine, with untrained models of the
  same architecture (latency doesn't depend on weights). Rerun on the gate hardware.
- **Licence:** Ultralytics YOLOv8 is AGPL-3.0, and that extends to trained weights.
  The repo code stays MIT; see ADR-0009.
- The plate repair (Phase 2) got one fix from the real OCR run: 1-digit districts outside
  Delhi now cost more (`KAOSMNO042` → `KA05MN0042`).

## Phase 2: Gate event engine

Branch: `phase-2-gate-event-engine`

- [x] OCR plate repair: tries every Indian plate layout, swaps look-alikes (O/0, I/1, B/8,
      S/5, Z/2, G/6, T/7, A/4) only where the layout needs the other kind, real state codes,
      HSRP "IND" prefix; bounded edit-distance fuzzy matcher. 50 table-driven read cases +
      9 edit-distance cases
- [x] Visit state machine as a pure module (all 56 status × trigger pairs tested); every
      change saved with a `visit_status_changes` row
- [x] Migration: `alerts`, `visit_status_changes`; `gate_events` gets `ocr_fixes`,
      `match_distance`, `paired_event_id`, `review_reason`, `reviewed_at/by`, review-queue index
- [x] Snapshot storage: local folder and S3-compatible (boto3); images checked by their bytes
- [x] Idempotency (unique event hash, race-safe) + debounce (Redis Lua, sliding window by
      capture time, fails open)
- [x] `POST /api/v1/gate-events` (device key, multipart): watchlist → unsure/unreadable
      (review) → resident vehicle → expected visitor → unknown
- [x] Resident exit closes the vehicle's open entry; visitor entry (APPROVED → INSIDE, with
      deadline) and exit (→ EXITED)
- [x] Staff APIs: list/filter events, snapshot download, review queue + correct/dismiss
      (saved to `plate_corrections`), alerts + acknowledge
- [x] Scripted-sequence test: a morning at the gate (`tests/api/test_gate_scenario.py`)
- [x] ADR-0005 (state machine), ADR-0006 (debounce + idempotency), ADR-0007 (storage +
      model changes), ADR-0008 (plate repair + fuzzy matching)
- [x] `docs/database.md`, `docs/api.md`, `.env.example`, `docs/learn/phase-2.md`
- [x] Verified locally: 355 tests on real Postgres 16 + Redis, 97% coverage overall, 99% on
      Phase 2 code; ruff, mypy, migrations up/down/up + `alembic check`; live API run as
      camera, guard and resident (debounce, alert, review, snapshot round trip, 403)
- [x] CI green, including the compose job's real S3 (RustFS) snapshot round trip
- [x] Merged: [PR #4](https://github.com/Akinchan-Jain-7/GateSense/pull/4)

### Notes and deviations from the brief

- **New tables and columns** beyond the brief's starting data model (`alerts`,
  `visit_status_changes`, review and pairing columns). Reasons in ADR-0007.
- **New dependencies:** `boto3` (S3 client for snapshots) and, for tests only, `moto`
  (in-memory fake S3). The brief lists S3-compatible storage but no client library.
  moto pulls in `cryptography`, which made PyJWT's types stricter; one test changed.
- **Plates now need a real state/UT code**, for typed plates too (`XX01AB1234` is a 422).
- **Visit time limits** are settings for now (guest 4 h, delivery 20 min, cab 10 min,
  service 2 h). Admin-configurable limits and resident-set service durations come with
  visitor registration in Phase 4, as the brief's phase plan says.
- **Nothing pushes to the guard console yet.** Alerts and review items are stored and
  listed; WebSocket push arrives in Phase 4.
- **Debounced reads are not stored**, and debounce is exact on the repaired plate (no fuzzy
  folding). The ANPR worker groups frames per car in Phase 3. See ADR-0006.
- **Housekeeping:** a local Redis dump file (`backend/dump.rdb`, test keys only) was
  committed by accident in two branch commits and removed in a follow-up commit;
  `dump.rdb` is now git-ignored. Rewriting already-pushed history was not allowed, so the
  file stays in the history of those two commits, but it is not in the repository's files.

## Phase 1: Backend core, database, auth

Branch: `phase-1-backend-core`

- [x] Settings (pydantic-settings, repo-root `.env`), JSON logging, request logs
- [x] `/health` (liveness) and `/ready` (Postgres + Redis, 503 when down)
- [x] SQLAlchemy models for the full data model (18 tables) + initial Alembic migration
- [x] `docs/database.md` with a Mermaid ER diagram; ADR-0003 (database layer and model changes)
- [x] Auth: Argon2id passwords, JWT access (15 min) + refresh (7 days, single-use, reuse
      detection), logout, `/me`; ADR-0004
- [x] RBAC via typed dependencies (`AdminUser`, `StaffUser`); device API keys (SHA-256, `X-Device-Key`)
- [x] CRUD with pagination and filters: flats, residents, vehicles, guards, gates, devices
      (+ key rotation), watchlist; society scoping; audit log for every admin change
- [x] Seed script: 40 flats, 60 residents, 80 vehicles, 3 guards, 2 gates, 4 devices, demo logins
- [x] Tests on real Postgres: 146 tests, 97% coverage overall, 97–99% per file in `services/`
- [x] CI: Postgres + Redis service containers; compose job runs migrations and checks `/ready`
- [x] `docs/api.md` (conventions + permission matrix), `docs/learn/phase-1.md`
- [x] Verified: full suite, ruff, mypy, gitleaks locally; CI green; live API checked as each role
- [x] Merged: [PR #2](https://github.com/Akinchan-Jain-7/GateSense/pull/2)

### Notes and deviations from the brief

- **Argon2id** was picked over bcrypt (the brief allows either). See ADR-0004.
- **Guards can read flats and vehicles.** Everything else in Phase 1 is admin-only. The
  guard console needs to look up flats and plates at the gate.
- **SQLAlchemy 2.1** is the current release; the brief says 2.0. Same API for everything we
  use.
- **Coverage** is measured but not enforced yet; CI gets a threshold in Phase 7 as planned.
- **Demo password** is `GateSense@123` (`DEMO_PASSWORD`). It is published on purpose for the demo.

## Phase 0: Repo foundation

Branch: `phase-0-repo-foundation`

- [x] Monorepo skeleton (§4 layout), MIT licence, `.gitignore`, `.editorconfig`, `.gitattributes`
- [x] `.env.example` with every variable documented
- [x] Pre-commit: ruff, ruff-format, mypy, prettier, eslint, end-of-file, large files, gitleaks
- [x] Placeholder backend: FastAPI `/health`, uv, strict mypy, pytest
- [x] Placeholder frontend: Vite + React + strict TypeScript, ESLint, Prettier, Vitest
- [x] `docker-compose.yml`: Postgres, Redis, Mailpit, S3-compatible storage, backend, frontend
- [x] CI: backend + frontend lint/test, compose smoke test, gitleaks
- [x] README skeleton, `CONTRIBUTING.md` (Conventional Commits), PR + issue templates
- [x] ADR-0001 (monorepo and tech stack), ADR-0002 (dev object storage, accepted)
- [x] `docs/learn/phase-0.md`
- [x] Verified: CI green, including `docker compose up` on a GitHub runner
- [x] Verified by the owner: Postgres, Redis, Mailpit and storage all healthy on Windows (Docker Desktop)

### Notes and deviations from the brief

- **MinIO → RustFS (accepted by the owner).** MinIO stopped publishing official Docker
  images in October 2025, and the community edition is archived. RustFS is a drop-in
  S3-compatible replacement. See [ADR-0002](adr/0002-dev-object-storage.md).
- **TypeScript 6.0, not 7.0.** TypeScript 7 (the native Go compiler) is out, but
  `typescript-eslint` does not support it yet. See ADR-0001.
- **`httpx2` instead of `httpx`.** Starlette's test client now asks for `httpx2` and warns
  about `httpx`. Same API.
- **uv** manages the Python packages (lockfile, fast installs). See ADR-0001.
- **Created in later phases, not as empty placeholders:** `anpr/Dockerfile` (Phase 3),
  `docker-compose.prod.yml` and `.github/workflows/deploy.yml` (Phase 8). The folders for
  every part of §4 already exist with a README explaining what goes there.
- **Docker images couldn't be pulled in the agent's own workspace** (registries blocked), so
  `docker compose up` was verified by the `compose` CI job on GitHub's runners instead.
