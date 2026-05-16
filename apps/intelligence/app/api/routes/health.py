import time

from fastapi import APIRouter

from app.infrastructure import check_health

router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health_check() -> dict:
    dep_status = await check_health()
    overall = "ok" if all(v == "ok" for v in dep_status.values()) else "degraded"

    return {
        "status": overall,
        "service": "cadence-intelligence",
        "version": "1.0.0",
        "uptime": round(time.time() - _start_time, 2),
        "dependencies": dep_status,
    }
