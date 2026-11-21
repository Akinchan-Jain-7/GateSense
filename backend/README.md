# GateSense backend

FastAPI service. Python 3.12, managed with [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync                       # create .venv and install everything
uv run uvicorn app.main:app --reload   # http://localhost:8000/docs
uv run pytest                 # tests
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

Folder guide (filled in from Phase 1 on):

| Folder | What lives there |
|---|---|
| `app/api/` | HTTP routers (v1). Thin: validate input, call a service, return a schema. |
| `app/core/` | Settings, security helpers, logging. |
| `app/db/` | Database session and base model. |
| `app/models/` | SQLAlchemy tables. |
| `app/schemas/` | Pydantic request/response models. |
| `app/services/` | Business logic (plate matching, visit state machine, …). |
| `app/workers/` | Celery background tasks. |
| `alembic/` | Database migrations. |
| `tests/` | pytest suite. |
