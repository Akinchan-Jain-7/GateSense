# ADR-0001: Monorepo and tech stack

- **Status:** Accepted
- **Date:** 2026-11-21

## Context

GateSense has several parts that change together: a FastAPI backend, a React frontend, an
ANPR (number-plate recognition) worker, a demo traffic simulator, load tests and docs. It is
built by one person, phase by phase, and must be easy to study for interviews.

## Decision

1. **One repository (monorepo)** with a top-level folder per part: `backend/`, `frontend/`,
   `anpr/`, `simulator/`, `loadtests/`, `scripts/`, `docs/`.
2. **Tech stack as listed in `CLAUDE.md` §3:** Python 3.12 + FastAPI + Pydantic v2,
   PostgreSQL + SQLAlchemy 2.0 + Alembic, Redis, Celery, React + TypeScript + Vite,
   Docker Compose, GitHub Actions.
3. **Tooling choices made in Phase 0:**
   - **uv** for Python packaging. It installs from a lockfile (`uv.lock`), so every machine
     and CI run gets the same versions, and it is much faster than pip.
   - **One shared `ruff.toml`** at the root, so every Python package follows the same rules.
   - **Strict type checking everywhere:** `mypy --strict` for Python; `strict: true` plus
     type-aware ESLint (`strictTypeChecked`) for TypeScript, with `any` banned.
   - **TypeScript 6.0** (pinned `~6.0.3`). TypeScript 7, the new native compiler, is
     released, but `typescript-eslint` (needed for ESLint on TypeScript) only supports up to
     6.0 at the moment. We move to 7 once it does.
   - **ESLint**, not oxlint. New Vite templates now default to oxlint, but the brief asks for
     ESLint, and its type-aware rules catch more bugs.
   - **`httpx2`** for API tests: Starlette's `TestClient` now recommends it over `httpx`.
4. **Every port is bound to `127.0.0.1`** in Docker Compose, so dev services aren't exposed to
   the network.

## Alternatives considered

- **One repo per service (polyrepo).** Cleaner boundaries, but cross-cutting changes (an API
  change plus the UI that uses it) would need several PRs, CI would be duplicated, and a
  recruiter would have to open several repos. Rejected.
- **pip + requirements.txt.** Familiar, but no real lockfile without extra tools. Rejected
  in favour of uv.
- **Poetry.** Works, but slower and heavier than uv. Rejected.

## Consequences

- One `docker compose up` starts the whole system, and one CI workflow checks it all.
- CI jobs run in parallel per part, so a frontend change doesn't wait on backend tests.
- Anyone working on the backend needs uv installed (one command; see `CONTRIBUTING.md`).
