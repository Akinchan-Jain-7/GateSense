"""GateSense API entry point.

Phase 0 placeholder: just enough of an app for Docker and CI to prove the
service starts. Settings, logging, routers and `/ready` arrive in Phase 1.
"""

from fastapi import FastAPI

app = FastAPI(
    title="GateSense API",
    version="0.1.0",
    description="AI-powered society gate and visitor management.",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness check: answers as long as the process is running."""
    return {"status": "ok"}
