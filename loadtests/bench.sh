#!/usr/bin/env bash
# Repeatable measurement: reseed, start one API process, warm up, then three runs.
# Reports the median of the three. Used for every number in docs/performance.md.
#
#   ./bench.sh <label> <backend dir> [extra vehicles]
#
# Needs Postgres + Redis running and backend/.env pointing at them.
set -euo pipefail
LABEL=$1
BACKEND=$(cd "$2" && pwd)
EXTRA_VEHICLES=${3:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
USERS=${USERS:-40}
# Local database URL for add_vehicles.py (git-ignored; see docs/performance.md).
if [ -f "$HERE/.env.local" ]; then set -a; . "$HERE/.env.local"; set +a; fi
DURATION=${DURATION:-40s}

pkill -f "uvicorn app.main" || true
sleep 1
(cd "$BACKEND" && uv run python -m app.seed --reset --no-history > /dev/null 2>&1)
if [ "$EXTRA_VEHICLES" -gt 0 ]; then
  (cd "$HERE" && uv run python add_vehicles.py "$EXTRA_VEHICLES")
fi
# A stress test sends far more than a real camera: lift the per-camera limit (Phase 7).
(cd "$BACKEND" && DEMO_MODE=true DEVICE_RATE_LIMIT=1000000 nohup uv run uvicorn app.main:app --port 8000 \
  --log-level warning > "/tmp/bench-$LABEL.log" 2>&1 &)
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1 && break; sleep 1; done

mkdir -p "$HERE/results"
cd "$HERE"
uv run locust --headless -u "$USERS" -r 20 -t 15s --host http://127.0.0.1:8000 \
  --only-summary > /dev/null 2>&1 || true  # warm-up, not counted
for i in 1 2 3; do
  uv run locust --headless -u "$USERS" -r 20 -t "$DURATION" --host http://127.0.0.1:8000 \
    --csv "results/$LABEL-$i" --only-summary > /dev/null 2>&1 || true  # failures are counted, not fatal
done
uv run python summarise.py "$LABEL"
