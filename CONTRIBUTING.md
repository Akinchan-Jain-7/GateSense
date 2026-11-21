# Contributing to GateSense

## One-time setup

Tools you need: **Git**, **Docker** (with Compose), **[uv](https://docs.astral.sh/uv/)**
(Python package manager) and **Node.js 22**.

```bash
# Python backend
cd backend && uv sync && cd ..

# Frontend
cd frontend && npm ci && cd ..

# Pre-commit hooks (run checks on every commit)
uv tool install pre-commit
pre-commit install
```

Install uv: `pip install uv`, or see the uv docs for a standalone installer.

## How we run things during development

**Supporting services run in Docker; our own code runs directly on your machine.**

- Postgres, Redis, Mailpit and object storage always run in Docker. That way there is one
  command, the same versions everywhere, and it's easy to reset. Redis has no official Windows
  build, so installing these natively would be harder.
- The backend and frontend run natively (`uv run …`, `npm run dev`) for fast reloads and easy
  debugging.
- CI also builds and starts the *whole* stack in Docker on every PR, so container problems
  show up early, not on deployment day. Production images are built in Phase 8.

```bash
# 1. Start the supporting services (leave this running)
docker compose up postgres redis mailpit storage

# 2. Backend, in a second terminal
cd backend
uv run alembic upgrade head                             # create / update the database schema
uv run python -m app.seed                               # demo data (first time only)
uv run uvicorn app.main:app --reload                    # http://localhost:8000/docs
uv run celery -A app.workers.celery_app worker --loglevel=info  # jobs (Windows: add --pool=solo)

# 3. Frontend, in a third terminal
cd frontend && npm run dev                              # http://localhost:5173
```

### Running the backend natively on Windows

- Use `127.0.0.1` (not `localhost`) in `DATABASE_URL`, `REDIS_URL` and `S3_ENDPOINT_URL`, as
  `.env.example` does. Windows tries `localhost` as IPv6 first, and the Docker ports listen
  on IPv4 only, so connections can stall. If Postgres can't be reached, commands now fail
  after 5 seconds instead of hanging.
- Start the API with `--reload` (as above). psycopg's async mode can't use Windows' default
  event loop; uvicorn switches to a compatible one when `--reload` is on. Without it, add
  `--loop app.core.event_loop:selector_event_loop`, or the API stops with that hint. The
  seed script and the tests pick the right loop themselves (`app/core/event_loop.py`).

### Docker Desktop troubleshooting (Windows)

`failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine` means the
Docker engine isn't running. Start **Docker Desktop**, wait for "Engine running", and check
with `docker info`. If Docker Desktop won't start:

- Install WSL 2: run `wsl --install` in an admin PowerShell, then restart.
- Check that virtualization is enabled: Task Manager → Performance → CPU → "Virtualization: Enabled".

## Everyday commands

| What | Command |
|---|---|
| Start supporting services | `docker compose up postgres redis mailpit storage` |
| Start everything in Docker | `docker compose up --build` |
| Backend tests | `cd backend && uv run pytest` (needs Postgres + Redis running) |
| Apply migrations | `cd backend && uv run alembic upgrade head` |
| New migration after a model change | `cd backend && uv run alembic revision --autogenerate -m "add X"` |
| Reset demo data | `cd backend && uv run python -m app.seed --reset` |
| Backend lint / types | `cd backend && uv run ruff check . && uv run mypy` |
| Frontend tests | `cd frontend && npm test` |
| Frontend lint / types | `cd frontend && npm run lint && npm run typecheck` |
| All pre-commit checks | `pre-commit run --all-files` |

## Branches and pull requests

- `main` is always green and deployable. Never push straight to it.
- Each phase is built on its own branch: `phase-N-short-name` (e.g. `phase-1-backend-core`).
- When a phase is finished, open a pull request into `main` and fill in the template.
  CI must pass before merging.

## Commit messages: Conventional Commits

Every commit message follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short summary in the imperative>

<optional body: what and why, not how>
```

**Types**

| Type | Use it for |
|---|---|
| `feat` | A new feature |
| `fix` | A bug fix (comes with a test that would have caught it) |
| `docs` | Documentation only |
| `test` | Adding or fixing tests |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `perf` | A performance improvement |
| `build` | Docker, dependencies, build tooling |
| `ci` | GitHub Actions workflows |
| `chore` | Housekeeping (configs, licence, renames) |

**Scopes** are the part of the repo: `api`, `backend`, `frontend`, `anpr`, `simulator`,
`db`, `infra`, `docs`.

**Examples**

```
feat(api): add visit state machine
fix(anpr): treat O as 0 only in digit positions
test(backend): add plate normaliser edge cases
docs: explain the debounce strategy in ADR-0004
```

Why bother? Small, labelled commits make the history readable ("what changed in the
escalation engine last week?"), make reviews easier, and let us generate release notes
automatically.

## Secrets

Never commit secrets. Only `.env.example` is tracked; your real `.env` is git-ignored.
Gitleaks scans every commit (pre-commit) and the whole history (CI). If it flags a false
positive, add a narrow, commented exception to `.gitleaks.toml`.
