import time

from fastapi import APIRouter

router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health_check() -> dict:
    return {
        "status": "ok",
        "service": "cadence-intelligence",
        "version": "0.0.0",
        "uptime": round(time.time() - _start_time, 2),
    }
