# Scripts

Helper scripts: demo reset (Phase 6) and other dev helpers.

Demo data seeding lives with the backend, because it uses the backend's models:
`cd backend && uv run python -m app.seed` (see `backend/app/seed.py`).

| Script | What it does |
|---|---|
| `webcam-demo.ps1` | Windows: laptop webcam as the gate camera, with the live preview ([docs/webcam-demo.md](../docs/webcam-demo.md)) |
| `oracle-cloud-init.sh` | One-paste setup of a fresh Ubuntu server for the live demo ([docs/deployment.md](../docs/deployment.md)) |
| `export_openapi.py` | Writes `frontend/openapi.json` for the typed API client |
