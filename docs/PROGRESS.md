# GateSense progress tracker

The build is split into phases (see `CLAUDE.md` §6). Each phase is one branch and one PR.
The agent updates this file at the start and end of every session.

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Repo foundation | ✅ Done | [#1](https://github.com/Akinchan-Jain-7/GateSense/pull/1) |
| 1 | Backend core, database, auth | ✅ Done | [#2](https://github.com/Akinchan-Jain-7/GateSense/pull/2) |
| 2 | Gate event engine | 🟡 In progress | |
| 3 | ANPR ML pipeline | ⚪ Not started | |
| 4 | Visitors, approvals, guest passes, real time | ⚪ Not started | |
| 5 | Escalation, notifications, scheduled jobs | ⚪ Not started | |
| 6 | Frontend (professional UI) | ⚪ Not started | |
| 7 | Hardening, offline mode, performance | ⚪ Not started | |
| 8 | Docker and deployment | ⚪ Not started | |
| 9 | Polish, docs, release | ⚪ Not started | |

**Now building:** Phase 2 (gate event engine).

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

## Phase 2: Gate event engine

Branch: `phase-2-gate-event-engine`

- [ ] OCR plate normaliser: Indian formats + state codes, position-aware look-alike fixes
      (O/0, I/1, B/8, S/5, Z/2…), bounded edit-distance fuzzy matcher; ≥40 table-driven tests
- [ ] Visit state machine as a pure module; illegal transitions raise; every change logged
      in a new `visit_status_changes` table
- [ ] Migration: `alerts` table, `visit_status_changes` table, new `gate_events` columns
      (pairing, match distance, review fields)
- [ ] Snapshot storage abstraction: local folder and S3-compatible (boto3), tested with moto
- [ ] Idempotency (event hash) + debounce (Redis cooldown per plate per lane, by capture time)
- [ ] `POST /api/v1/gate-events` (device key, multipart with snapshot) running the matching
      pipeline: watchlist → resident vehicle → open visit → unknown; low confidence → review
- [ ] Resident entry/exit pairing; visitor entry (APPROVED → INSIDE) and exit (→ EXITED)
- [ ] Guard APIs: list events, snapshot download, review queue + correction (saved to
      `plate_corrections`), alerts + acknowledge
- [ ] Scripted-sequence integration test (visits, alerts, review items)
- [ ] ADRs: visit state machine, debounce strategy, snapshot storage + model changes
- [ ] `docs/database.md`, `docs/api.md`, `.env.example`, `docs/learn/phase-2.md`
- [ ] Verified: full suite, ruff, mypy, live API run; CI green (compose job posts a real
      event with a snapshot to S3 storage)

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
