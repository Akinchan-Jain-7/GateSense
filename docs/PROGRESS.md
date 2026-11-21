# GateSense progress tracker

The build is split into phases (see `CLAUDE.md` §6). Each phase is one branch and one PR.
The agent updates this file at the start and end of every session.

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Repo foundation | ✅ Done | [#1](https://github.com/Akinchan-Jain-7/GateSense/pull/1) |
| 1 | Backend core, database, auth | ✅ Done | [#2](https://github.com/Akinchan-Jain-7/GateSense/pull/2) |
| 2 | Gate event engine | ✅ Done | [#4](https://github.com/Akinchan-Jain-7/GateSense/pull/4) |
| 3 | ANPR ML pipeline | ✅ Done (model accuracy pending owner Colab runs) | [#6](https://github.com/Akinchan-Jain-7/GateSense/pull/6) |
| 4 | Visitors, approvals, guest passes, real time | ⚪ Not started | |
| 5 | Escalation, notifications, scheduled jobs | ⚪ Not started | |
| 6 | Frontend (professional UI) | ⚪ Not started | |
| 7 | Hardening, offline mode, performance | ⚪ Not started | |
| 8 | Docker and deployment | ⚪ Not started | |
| 9 | Polish, docs, release | ⚪ Not started | |

**Next up:** Phase 4 (visitors, approvals, guest passes, real time).

**Waiting on the owner:** run `anpr/notebooks/01_train_plate_detector.ipynb` and
`02_evaluate_ocr.ipynb` in Colab (see the Phase 3 section).

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
