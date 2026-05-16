from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from app.infrastructure import get_db_pool

logger = structlog.get_logger()


async def fetch_observations(
    endpoint_id: str,
    segmentation_key: str,
    window_start: str,
    window_end: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    rows = await pool.fetch(
        """
        SELECT time, endpoint_id, request_id, status_code, latency_ms,
               request_size_bytes, response_size_bytes, segmentation_key,
               payload_hash, payload_sample, region, deployment_id, metadata
        FROM observations
        WHERE endpoint_id = $1
          AND segmentation_key = $2
          AND time >= $3::timestamptz
          AND time <= $4::timestamptz
        ORDER BY time DESC
        LIMIT $5
        """,
        endpoint_id,
        segmentation_key,
        window_start,
        window_end,
        limit,
    )

    observations: list[dict[str, Any]] = []
    for row in rows:
        obs = dict(row)
        if obs.get("payload_sample") and isinstance(obs["payload_sample"], str):
            try:
                obs["payload_sample"] = json.loads(obs["payload_sample"])
            except (json.JSONDecodeError, TypeError):
                obs["payload_sample"] = None
        if obs.get("metadata") and isinstance(obs["metadata"], str):
            try:
                obs["metadata"] = json.loads(obs["metadata"])
            except (json.JSONDecodeError, TypeError):
                obs["metadata"] = {}
        observations.append(obs)

    return observations


async def insert_feature_vector(
    endpoint_id: str,
    segmentation_key: str,
    window_start: str,
    window_end: str,
    sample_count: int,
    features_json: str,
    model_version: str,
) -> None:
    pool = await get_db_pool()
    now = datetime.now(UTC).isoformat()
    await pool.execute(
        """
        INSERT INTO feature_vectors (time, endpoint_id, segmentation_key, window_start, window_end, sample_count, features, model_version, computed_at)
        VALUES ($1::timestamptz, $2, $3, $4::timestamptz, $5::timestamptz, $6, $7::jsonb, $8, NOW())
        """,
        now,
        endpoint_id,
        segmentation_key,
        window_start,
        window_end,
        sample_count,
        features_json,
        model_version,
    )


async def fetch_active_baseline(
    endpoint_id: str,
    segmentation_key: str,
) -> dict[str, Any] | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT time, baseline, sample_count, window_days, maturity_state, confidence_score
        FROM baseline_snapshots
        WHERE endpoint_id = $1
          AND segmentation_key = $2
          AND is_active = true
        ORDER BY time DESC
        LIMIT 1
        """,
        endpoint_id,
        segmentation_key,
    )

    if not row:
        return None

    return dict(row)


async def insert_drift_score(
    endpoint_id: str,
    segmentation_key: str,
    score: float,
    components_json: str,
    alert_triggered: bool,
    model_version: str,
    baseline_snapshot_time: str | None = None,
) -> None:
    pool = await get_db_pool()
    now = datetime.now(UTC).isoformat()
    await pool.execute(
        """
        INSERT INTO drift_scores (time, endpoint_id, segmentation_key, score, components, alert_triggered, alert_id, model_version, baseline_snapshot_time)
        VALUES ($1::timestamptz, $2, $3, $4, $5::jsonb, $6, NULL, $7, $8::timestamptz)
        """,
        now,
        endpoint_id,
        segmentation_key,
        score,
        components_json,
        alert_triggered,
        model_version,
        baseline_snapshot_time,
    )


async def insert_feature_vector_and_drift_score(
    endpoint_id: str,
    segmentation_key: str,
    fv_window_start: str,
    fv_window_end: str,
    fv_sample_count: int,
    fv_features_json: str,
    fv_model_version: str,
    drift_score: float,
    drift_components_json: str,
    drift_alert_triggered: bool,
    drift_model_version: str,
    baseline_snapshot_time: str | None = None,
) -> None:
    pool = await get_db_pool()
    now = datetime.now(UTC).isoformat()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO feature_vectors (time, endpoint_id, segmentation_key, window_start, window_end, sample_count, features, model_version, computed_at)
                VALUES ($1::timestamptz, $2, $3, $4::timestamptz, $5::timestamptz, $6, $7::jsonb, $8, NOW())
                """,
                now,
                endpoint_id,
                segmentation_key,
                fv_window_start,
                fv_window_end,
                fv_sample_count,
                fv_features_json,
                fv_model_version,
            )
            await conn.execute(
                """
                INSERT INTO drift_scores (time, endpoint_id, segmentation_key, score, components, alert_triggered, alert_id, model_version, baseline_snapshot_time)
                VALUES ($1::timestamptz, $2, $3, $4, $5::jsonb, $6, NULL, $7, $8::timestamptz)
                """,
                now,
                endpoint_id,
                segmentation_key,
                drift_score,
                drift_components_json,
                drift_alert_triggered,
                drift_model_version,
                baseline_snapshot_time,
            )


async def check_idempotency_key(redis_client: Any, key: str, ttl_seconds: int = 900) -> bool:
    result = await redis_client.set(key, "1", nx=True, ex=ttl_seconds)
    return result is not None


async def fetch_feature_vectors_for_baseline(
    endpoint_id: str,
    segmentation_key: str,
    window_days: int = 7,
    limit: int = 500,
) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    rows = await pool.fetch(
        """
        SELECT time, endpoint_id, segmentation_key, window_start, window_end,
               sample_count, features, model_version, computed_at
        FROM feature_vectors
        WHERE endpoint_id = $1
          AND segmentation_key = $2
          AND time >= NOW() - make_interval(days => $3)
        ORDER BY time ASC
        LIMIT $4
        """,
        endpoint_id,
        segmentation_key,
        window_days,
        limit,
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        if r.get("features") and isinstance(r["features"], str):
            try:
                r["features"] = json.loads(r["features"])
            except (json.JSONDecodeError, TypeError):
                r["features"] = {}
        result.append(r)
    return result


async def insert_baseline_snapshot(
    endpoint_id: str,
    segmentation_key: str,
    window_days: int,
    sample_count: int,
    baseline_json: str,
    confidence_score: float,
    maturity_state: str,
) -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE baseline_snapshots
                SET is_active = false
                WHERE endpoint_id = $1
                  AND segmentation_key = $2
                  AND is_active = true
                """,
                endpoint_id,
                segmentation_key,
            )
            await conn.execute(
                """
                INSERT INTO baseline_snapshots
                    (time, endpoint_id, segmentation_key, window_days, sample_count,
                     baseline, confidence_score, maturity_state, is_active, created_at)
                VALUES (NOW(), $1, $2, $3, $4, $5::jsonb, $6, $7, true, NOW())
                """,
                endpoint_id,
                segmentation_key,
                window_days,
                sample_count,
                baseline_json,
                confidence_score,
                maturity_state,
            )


async def update_endpoint_maturity(
    endpoint_id: str,
    maturity_state: str,
    observation_count: int | None = None,
) -> None:
    pool = await get_db_pool()
    if observation_count is not None:
        await pool.execute(
            """
            UPDATE endpoints
            SET maturity_state = $2,
                observation_count = $3,
                last_observed_at = NOW()
            WHERE id = $1
            """,
            endpoint_id,
            maturity_state,
            observation_count,
        )
    else:
        await pool.execute(
            """
            UPDATE endpoints
            SET maturity_state = $2
            WHERE id = $1
            """,
            endpoint_id,
            maturity_state,
        )


async def fetch_recent_deployment(
    project_id: str,
) -> dict[str, Any] | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, project_id, version, environment, deployed_at, metadata, created_at
        FROM deployments
        WHERE project_id = $1
        ORDER BY deployed_at DESC
        LIMIT 1
        """,
        project_id,
    )
    if not row:
        return None
    return dict(row)


async def fetch_endpoint_by_id(
    endpoint_id: str,
) -> dict[str, Any] | None:
    pool = await get_db_pool()
    row = await pool.fetchrow(
        """
        SELECT id, project_id, route_template, method, display_name, config,
               maturity_state, observation_count, last_observed_at, created_at
        FROM endpoints
        WHERE id = $1 AND deleted_at IS NULL
        """,
        endpoint_id,
    )
    if not row:
        return None
    r = dict(row)
    if r.get("config") and isinstance(r["config"], str):
        try:
            r["config"] = json.loads(r["config"])
        except (json.JSONDecodeError, TypeError):
            r["config"] = {}
    return r
