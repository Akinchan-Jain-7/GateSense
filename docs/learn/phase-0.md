# Phase 0 study guide: Repo foundation

## What we built and why

Before writing any product code, we set up the "workshop": one repository for every part of
GateSense, a one-command local stack (`docker compose up`), automatic quality checks on every
commit (pre-commit) and on every pull request (GitHub Actions CI), and the documents that
explain our decisions. The backend and frontend are tiny placeholders: a FastAPI app with a
`/health` endpoint and a React page. Their job is to prove the pipeline works end to end, so
that from Phase 1 on every real feature is linted, type-checked, tested and run in Docker
automatically.

## Key concepts, explained simply

**Monorepo.** One Git repository holding several projects (backend, frontend, ANPR worker…).
A change that touches the API *and* the UI is one commit and one PR, and CI checks both.

**Docker image vs container.** An *image* is a frozen recipe: an OS, Python, our code and
its libraries. A *container* is a running copy of that image. Every developer and CI run uses
the same image, so "works on my machine" problems mostly disappear.

**Docker Compose.** A YAML file (`docker-compose.yml`) that lists several containers
(Postgres, Redis, Mailpit, storage, backend, frontend), how they connect, and which ports
they open. `docker compose up` starts them all in the right order.

**Healthcheck.** A small command Docker runs every few seconds to ask "are you actually
ready?" (for example `pg_isready` for Postgres). A container can be *running* but not yet
*healthy*. `depends_on: condition: service_healthy` makes the backend wait for a healthy
database, not just a started one.

**CI (Continuous Integration).** A robot (GitHub Actions) that, on every pull request,
installs the project from scratch on a clean machine and runs lint, type checks, tests, and
our Docker stack. If anything fails, the PR shows a red ❌ and we don't merge.

**Pre-commit hooks.** The same kind of checks, run on *your* machine every time you
`git commit`, so mistakes are caught before they ever reach GitHub.

**Linter, formatter, type checker.**
- A *formatter* (ruff format, Prettier) fixes layout: spacing, quotes, line length.
- A *linter* (ruff, ESLint) finds likely bugs and bad patterns, like an unused variable or a bare `except:`.
- A *type checker* (mypy, `tsc`) proves that types line up, e.g. you never pass a string
  where a number is expected. We run both in **strict** mode.

**Secret scanning (gitleaks).** Searches commits for things that look like passwords or API
keys. Once a secret is pushed to GitHub it should be considered leaked, so we block it early.

**Lockfile.** `uv.lock` (Python) and `package-lock.json` (Node) record the *exact* version of
every library, so everyone installs exactly the same thing.

**ADR (Architecture Decision Record).** A short document: the problem, the decision, the
alternatives, and the consequences. Future you (or an interviewer) can see *why*, not just *what*.

**Conventional Commits.** A commit message format like `feat(api): add login`. The type
(`feat`, `fix`, `docs`, …) makes history easy to scan and release notes easy to generate.

## Files to read, in order

1. `README.md`: the recruiter-facing front page; notice every number is "TBD", never invented.
2. `docs/adr/0001-monorepo-and-tech-stack.md`: why one repo, why uv, why TypeScript 6.
3. `docs/adr/0002-dev-object-storage.md`: how we handled MinIO disappearing. A good
   "how do you deal with a dependency going away?" story.
4. `docker-compose.yml`: notice the healthchecks, `depends_on` conditions, named volumes,
   and that every port is bound to `127.0.0.1`.
5. `.env.example`: every setting the stack reads, with safe defaults; the real `.env` is git-ignored.
6. `backend/app/main.py` and `backend/tests/test_health.py`: the smallest possible FastAPI
   app and its test.
7. `backend/pyproject.toml`: dependencies, plus pytest and strict mypy settings.
8. `backend/Dockerfile`: notice dependencies are installed *before* the code is copied (layer caching).
9. `frontend/src/app/App.tsx` and `frontend/tests/App.test.tsx`: a component and a test
   that finds it the way a user would (by its heading role).
10. `frontend/eslint.config.js`: type-aware strict rules; `any` is an error.
11. `.pre-commit-config.yaml`: which checks run on every commit.
12. `.github/workflows/ci.yml`: four parallel jobs; the `compose` job starts the full stack
    and curls each service.
13. `CONTRIBUTING.md`: setup steps and the commit-message rules.

## Decisions made and alternatives rejected

| Decision | Rejected alternatives | Why |
|---|---|---|
| Monorepo | Repo per service | One PR per change, one CI, one place for recruiters to look. |
| uv for Python | pip + requirements.txt, Poetry | Real lockfile and very fast installs. |
| RustFS for local S3 | MinIO, community MinIO rebuilds | MinIO stopped publishing images; RustFS is maintained and S3-compatible. |
| TypeScript 6.0 | TypeScript 7.0 | ESLint's TypeScript support doesn't handle 7.0 yet. |
| ESLint | oxlint (new Vite default) | Brief asks for ESLint; type-aware rules catch more bugs. |
| Ports bound to 127.0.0.1 | `0.0.0.0` (Docker's default) | Dev databases with default passwords shouldn't be reachable from your Wi-Fi. |
| CI runs `docker compose up` | Only unit tests in CI | Proves the containers really start, so nobody discovers a broken Dockerfile later. |

## Likely interview questions

1. **Why a monorepo?** One person, tightly connected parts: a feature that changes the API and
   the UI is one PR, CI checks everything together, and the code is easy to navigate.
2. **What's the difference between an image and a container?** An image is the read-only
   template; a container is a running instance of it with its own writable layer.
3. **Why do you need healthchecks if the container is already running?** "Running" means the
   process started; "healthy" means it can serve requests. Postgres takes a few seconds to
   accept connections, so the backend waits for healthy, not just started.
4. **How do you stop secrets from leaking?** Only `.env.example` is committed, `.env` is
   ignored, and gitleaks scans each commit locally and the full history in CI.
5. **What does CI check on every PR?** Backend: ruff lint and format, strict mypy, pytest
   with coverage. Frontend: ESLint, Prettier, `tsc`, Vitest, production build. Plus a full
   Docker Compose start-up and a secret scan.
6. **Why put dependency install before `COPY . .` in a Dockerfile?** Docker caches each
   layer. If only code changed, the slow install layer is reused, so rebuilds take seconds.
7. **What would you do if a key dependency (like MinIO) stopped being distributed?** Check how
   tightly we depend on it. We only use the standard S3 API, so we swapped in a compatible
   server and recorded the decision in an ADR.
8. **Why lockfiles?** Reproducible builds: same versions on every laptop, in CI and in prod,
   so a library releasing a breaking change doesn't silently break us.
9. **What's the difference between a linter and a type checker?** The linter flags suspicious
   patterns and style; the type checker proves type correctness across function boundaries.
   They catch different bugs, so we run both.
10. **What are Conventional Commits and why use them?** A `type(scope): summary` format that
    makes history searchable and lets tools generate changelogs and version bumps.

## Exercise

Break the build on purpose and watch the checks catch it:

1. In `backend/app/main.py`, change `return {"status": "ok"}` to `return {"status": 1}`.
2. Run `cd backend && uv run mypy`. What error do you get, and why? (Hint: look at the
   function's return type.)
3. Run `uv run pytest`. Which test fails?
4. Undo the change. Bonus: start the stack with `docker compose up --build`, open
   http://localhost:8000/docs and call `/health` from the browser.
