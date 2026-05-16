from __future__ import annotations

import os
import socket
import uuid

import asyncpg
import redis.asyncio as aioredis
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = structlog.get_logger()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

if REDIS_PASSWORD:
    REDIS_URL = os.getenv("REDIS_URL", f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}")
else:
    REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}")

DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_USER = os.getenv("DATABASE_USER", "cadence")
DB_PASS = os.getenv("DATABASE_PASSWORD", "devpassword")
DB_NAME = os.getenv("DATABASE_NAME", "cadence_dev")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}",
)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

PG_POOL_MIN = int(os.getenv("PG_POOL_MIN", "5"))
PG_POOL_MAX = int(os.getenv("PG_POOL_MAX", "20"))
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))


_redis_pool: aioredis.Redis | None = None
_pg_pool: asyncpg.Pool | None = None


def generate_worker_id() -> str:
    hostname = socket.gethostname()
    pid = os.getpid()
    suffix = uuid.uuid4().hex[:8]
    return f"{hostname}-{pid}-{suffix}"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((ConnectionError, OSError, asyncpg.PostgresError)),
    reraise=True,
)
async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=REDIS_MAX_CONNECTIONS,
        )
        await _redis_pool.ping()
        logger.info("redis_connected", url=REDIS_URL[:20] + "...")
    return _redis_pool


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((ConnectionError, OSError, asyncpg.PostgresError)),
    reraise=True,
)
async def get_db_pool() -> asyncpg.Pool:
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=PG_POOL_MIN,
            max_size=PG_POOL_MAX,
        )
        async with _pg_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        logger.info("pg_pool_connected", min_size=PG_POOL_MIN, max_size=PG_POOL_MAX)
    return _pg_pool


async def close_connections() -> None:
    global _redis_pool, _pg_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("redis_disconnected")
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None
        logger.info("pg_pool_disconnected")


async def check_health() -> dict[str, str]:
    status: dict[str, str] = {"redis": "unknown", "postgres": "unknown"}
    try:
        r = await get_redis()
        await r.ping()
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "error"
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        status["postgres"] = "ok"
    except Exception:
        status["postgres"] = "error"
    return status
