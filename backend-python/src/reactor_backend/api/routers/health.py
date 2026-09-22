from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from reactor_backend.infrastructure.database import DatabaseProtocol

router = APIRouter(prefix="/internal/health", tags=["internal-health"])


@router.get("/live")
async def live(request: Request) -> dict[str, str]:
    return {"status": "UP", "service": request.app.state.settings.app_name}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    database: DatabaseProtocol = request.app.state.database
    timeout_seconds: float = request.app.state.settings.database_ready_timeout_seconds
    try:
        async with asyncio.timeout(timeout_seconds):
            await database.ping()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "DOWN", "checks": {"mysql": "DOWN"}},
        )
    return JSONResponse(content={"status": "UP", "checks": {"mysql": "UP"}})
