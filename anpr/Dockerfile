# ANPR worker image (edge machine at the gate). Ships without an OCR engine by default;
# build with --build-arg OCR_EXTRA=easyocr (or paddleocr) for camera use. The model file is
# mounted or downloaded at start (python -m gatesense_anpr.download_model), never baked in.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/

# OpenCV needs these shared libraries even in its headless build.
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
ARG OCR_EXTRA=""
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project ${OCR_EXTRA:+--extra $OCR_EXTRA}
COPY gatesense_anpr ./gatesense_anpr
COPY eval ./eval
RUN uv sync --frozen --no-dev ${OCR_EXTRA:+--extra $OCR_EXTRA}

# Offline mode: reads that can't be delivered wait here. Mount a volume on /data so they
# survive a container restart: docker run -v anpr-buffer:/data ...
ENV ANPR_BUFFER_PATH=/data/offline-buffer.sqlite3
VOLUME ["/data"]

# Default: a simulated camera (no model needed). Override the command for a real source.
CMD ["gatesense-anpr", "--simulate", "1000", "--realtime", "--interval", "5"]
