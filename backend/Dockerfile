# Backend image, two targets:
#   dev  (docker-compose.yml):      every dependency, live reload, code mounted from your disk
#   prod (docker-compose.prod.yml): no dev tools, non-root, healthcheck; the same image runs
#                                    the API, the Celery worker and Celery Beat (only the
#                                    command differs).
FROM python:3.12-slim AS base

# uv installs dependencies from uv.lock, so every build gets identical versions.
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./


# --- Development ---------------------------------------------------------------------
FROM base AS dev

# Dependencies first (a cached layer), code afterwards: editing code doesn't reinstall.
RUN uv sync --frozen --no-install-project
COPY . .
EXPOSE 8000
# Apply database migrations, then start the API with live reload.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]


# --- Production: build the virtual environment ---------------------------------------
FROM base AS build

RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app


# --- Production: the image that runs -------------------------------------------------
# A fresh slim image: no uv, no build cache, only the venv and the code.
FROM python:3.12-slim AS prod

# FORWARDED_ALLOW_IPS (read by uvicorn): trust X-Forwarded-For from the reverse proxy in
# front of the API, so rate limits see the real client address. "*" is right when only the
# proxy can reach the API (the prod compose file publishes no API port); narrow it otherwise.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    SNAPSHOT_LOCAL_DIR=/data/snapshots \
    FORWARDED_ALLOW_IPS="*"

# A system user with no shell and no home: if the app is ever compromised, it can't
# change its own code or anything else in the image.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin gatesense \
    && mkdir -p /data/snapshots && chown -R gatesense /data

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app /app

USER gatesense
# Snapshots (when SNAPSHOT_STORAGE=local) live here: mount a volume so they survive.
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# WEB_CONCURRENCY (read by uvicorn) sets the number of worker processes; default 1.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
