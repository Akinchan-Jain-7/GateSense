# GateSense backend

FastAPI service. Python 3.12, managed with [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync                                  # create .venv and install everything
uv run alembic upgrade head              # create / update the database schema
uv run python -m app.seed                # demo data (--reset to start over)
uv run uvicorn app.main:app --reload     # http://localhost:8000/docs
uv run pytest --cov                      # tests (Postgres + Redis must be running)
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Settings come from environment variables or the repo-root `.env` (see `.env.example`).
Tests create their own database, `<DATABASE_URL database>_test`, or use `TEST_DATABASE_URL`.

How a request flows: **router** (`app/api/v1/`, HTTP only) → **service** (`app/services/`,
business rules, raises `NotFoundError` / `ConflictError` / …) → **models** (`app/models/`).
`app/api/errors.py` maps service errors to status codes. See `docs/learn/phase-1.md`.

Folder guide:

| Folder | What lives there |
|---|---|
| `app/api/` | `deps.py` (auth, roles, paging), `errors.py`, `system.py` (`/health`, `/ready`), `v1/` routers. Thin: validate input, call a service, return a schema. |
| `app/core/` | Settings, security helpers, logging. |
| `app/db/` | Database session and base model. |
| `app/models/` | SQLAlchemy tables. |
| `app/schemas/` | Pydantic request/response models. |
| `app/services/` | Business logic (plate matching, visit state machine, …). |
| `app/workers/` | Celery background tasks. |
| `alembic/` | Database migrations. |
| `app/seed.py` | Demo data generator (`python -m app.seed`). |
| `tests/` | pytest suite: `unit/`, `api/`, migrations, seed. `conftest.py` explains the isolation. |
