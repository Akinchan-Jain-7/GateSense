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

## Everyday commands

| What | Command |
|---|---|
| Start everything | `docker compose up --build` |
| Backend tests | `cd backend && uv run pytest` |
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
