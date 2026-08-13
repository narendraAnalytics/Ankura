"""GET /healthz (liveness, no DB) and GET /readyz (readiness, real DB round
trip).

Implemented in Phase 1 Step 8.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from ankura.db.engine import ping

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness — no DB access. If this doesn't respond, the process itself
    is dead, not just its database connection."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness — a real `SELECT 1` round trip."""
    if await ping():
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready"})
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "not_ready"}
    )
