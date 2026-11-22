# Demo traffic simulator: drives the live demo through the public API, like real cameras,
# a guard and residents would. Small image: Python + httpx + Pillow, no ML.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY gatesense_sim ./gatesense_sim
COPY README.md ./
RUN uv sync --frozen --no-dev

# It only makes HTTP calls, so it never needs root.
RUN useradd --system --uid 10001 sim
USER sim

# Settings come from the environment: SIM_API_URL, SIM_PASSWORD, SIM_SPEED, ...
CMD ["gatesense-sim"]
