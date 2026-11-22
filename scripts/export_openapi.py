"""Write the backend's OpenAPI schema to frontend/openapi.json.

The frontend's API types (src/lib/api/schema.d.ts) are generated from this file, so the
two can't drift apart: CI regenerates both and fails if the committed copies differ.

    cd backend && uv run python ../scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

# Run from backend/: make `app` importable however the script is started.
sys.path.insert(0, str(Path.cwd()))

from app.main import app  # noqa: E402

target = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"
target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {target}")
