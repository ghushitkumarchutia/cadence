from __future__ import annotations

import asyncio
import json
import signal
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.baseline_computer import compute_baseline, resolve_maturity_state
from app.core.confidence_scorer import compute_confidence, should_alert
from app.core.drift_scorer import score_drift
from app.core.feature_extractor import extract_features
from app.core.summary_generator import generate_alert_summary
from app.db.queries import (
    check_idempotency_key,
    fetch_active_baseline,
    fetch_endpoint_by_id,
    fetch_feature_vectors_for_baseline,
    fetch_observations,
    fetch_recent_deployment,
    insert_baseline_snapshot,
    insert_feature_vector_and_drift_score,
    update_endpoint_maturity,
)
from app.infrastructure import generate_worker_id, get_db_pool, get_redis
from app.schemas.features import FeatureVectorData, ResponseLevelFeatures, FieldFeatures
from app.schemas.scoring import BaselineData

logger = structlog.get_logger()

STREAM_KEY = "cadence:observations"
CONSUMER_GROUP = "intelligence-group"
DRIFT_STREAM_KEY = "cadence:drift-scores"
BASELINE_REQUEST_KEY = "cadence:baseline-requests"
BASELINE_CONSUMER_GROUP = "baseline-group"
DEAD_LETTER_KEY = "cadence:dead-letters"
BATCH_SIZE = 50
BLOCK_MS = 5000
FEATURE_TRIGGER_COUNT = 100
FEATURE_TRIGGER_INTERVAL_S = 900
MAX_DELIVERY_ATTEMPTS = 5
RECOVERY_INTERVAL_S = 60
IDLE_TIME_MS = 60000
DRAIN_TIMEOUT_S = 10
PERSISTENCE_KEY_PREFIX = "drift:persist"
PERSISTENCE_RESET_THRESHOLD = 2.0
PERSISTENCE_INCREMENT_THRESHOLD = 4.0
PERSISTENCE_TTL_S = 86400


class StreamWorker:
    def __init__(self) -> None:
        self._running = False
        self._consumer_name = generate_worker_id()
        self._observation_counts: dict[str, int] = {}
        self._last_extraction: dict[str, float] = {}
        self._processing = False

    async def start(self) -> None:
        redis = await get_redis()
        await get_db_pool()
        self._running = True

        try:
            await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

        try:
            await redis.xgroup_create(BASELINE_REQUEST_KEY, BASELINE_CONSUMER_GROUP, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise

        logger.info(
            "stream_worker_started",
            consumer=self._consumer_name,
            stream=STREAM_KEY,
        )

        await self._drain_pending()

        recovery_task = asyncio.create_task(self._recovery_loop())
        baseline_task = asyncio.create_task(self._baseline_consume_loop())

        try:
            while self._running:
                try:
                    await self._consume_batch()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("stream_worker_consume_error", error=str(exc))
                    await asyncio.sleep(1.0)
        finally:
            recovery_task.cancel()
            baseline_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass
            try:
                await baseline_task
            except asyncio.CancelledError:
                pass

        await self._drain()
        logger.info("stream_worker_stopped", consumer=self._consumer_name)

    async def stop(self) -> None:
        self._running = False

    async def _drain(self) -> None:
        if self._processing:
            logger.info("stream_worker_draining")
            deadline = asyncio.get_event_loop().time() + DRAIN_TIMEOUT_S
            while self._processing and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.1)

    async def _drain_pending(self) -> None:
        redis = await get_redis()
        while True:
            messages = await redis.xreadgroup(
                CONSUMER_GROUP,
                self._consumer_name,
                {STREAM_KEY: "0"},
                count=BATCH_SIZE,
            )
            if not messages:
                break

            has_data = False
            for stream_name, stream_messages in messages:
                if not stream_messages:
                    continue
                has_data = True
                for msg_id, msg_data in stream_messages:
                    if not msg_data:
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                        continue
                    try:
                        await self._process_message(msg_id, msg_data)
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        logger.error(
                            "pending_message_processing_failed",
                            msg_id=msg_id,
                            error=str(exc),
                        )

            if not has_data:
                break

    async def _consume_batch(self) -> None:
        redis = await get_redis()

        messages = await redis.xreadgroup(
            CONSUMER_GROUP,
            self._consumer_name,
            {STREAM_KEY: ">"},
            count=BATCH_SIZE,
            block=BLOCK_MS,
        )

        if not messages:
            return

        self._processing = True
        try:
            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    try:
                        await self._process_message(msg_id, msg_data)
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        logger.error(
                            "message_processing_failed",
                            msg_id=msg_id,
                            error=str(exc),
                        )
        finally:
            self._processing = False

    async def _recovery_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(RECOVERY_INTERVAL_S)
                await self._recover_pending_messages()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("recovery_loop_error", error=str(exc))

    async def _recover_pending_messages(self) -> None:
        redis = await get_redis()
        cursor = "0-0"

        while True:
            result = await redis.xautoclaim(
                STREAM_KEY,
                CONSUMER_GROUP,
                self._consumer_name,
                min_idle_time=IDLE_TIME_MS,
                start_id=cursor,
                count=BATCH_SIZE,
            )

            if not result or len(result) < 2:
                break

            next_cursor = result[0]
            claimed_messages = result[1]

            if not claimed_messages:
                break

            for msg_id, msg_data in claimed_messages:
                if not msg_data:
                    continue

                pending_info = await redis.xpending_range(
                    STREAM_KEY, CONSUMER_GROUP, min=msg_id, max=msg_id, count=1,
                )

                delivery_count = 0
                if pending_info:
                    delivery_count = pending_info[0].get("times_delivered", 0) if isinstance(pending_info[0], dict) else 0

                if delivery_count >= MAX_DELIVERY_ATTEMPTS:
                    logger.warning(
                        "message_sent_to_dead_letter",
                        msg_id=msg_id,
                        delivery_count=delivery_count,
                    )
                    dead_letter_data: dict[Any, Any] = dict(msg_data)
                    dead_letter_data["original_id"] = msg_id
                    dead_letter_data["delivery_count"] = str(delivery_count)
                    dead_letter_data["dead_lettered_at"] = datetime.now(UTC).isoformat()
                    await redis.xadd(DEAD_LETTER_KEY, dead_letter_data, maxlen=10000)
                    await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                    continue

                try:
                    await self._process_message(msg_id, msg_data)
                    await redis.xack(STREAM_KEY, CONSUMER_GROUP, msg_id)
                except Exception as exc:
                    logger.error(
                        "recovered_message_failed",
                        msg_id=msg_id,
                        delivery_count=delivery_count,
                        error=str(exc),
                    )

            if next_cursor == "0-0" or next_cursor == b"0-0":
                break
            cursor = next_cursor

    async def _process_message(self, msg_id: str, data: dict[str, str]) -> None:
        endpoint_id = data.get("endpoint_id", "")
        segmentation_key = data.get("segmentation_key", "default")
        cache_key = f"{endpoint_id}:{segmentation_key}"

        self._observation_counts[cache_key] = self._observation_counts.get(cache_key, 0) + 1
        now = asyncio.get_event_loop().time()
        last_extraction = self._last_extraction.get(cache_key, 0.0)

        count = self._observation_counts[cache_key]
        elapsed = now - last_extraction

        if count >= FEATURE_TRIGGER_COUNT or elapsed >= FEATURE_TRIGGER_INTERVAL_S:
            await self._trigger_feature_extraction(endpoint_id, segmentation_key, data)
            self._observation_counts[cache_key] = 0
            self._last_extraction[cache_key] = now

    async def _trigger_feature_extraction(
        self,
        endpoint_id: str,
        segmentation_key: str,
        msg_data: dict[str, str],
    ) -> None:
        now = datetime.now(UTC)
        window_end = now
        window_start = now.replace(
            minute=(now.minute // 15) * 15,
            second=0,
            microsecond=0,
        )

        idempotency_key = f"fv:idem:{endpoint_id}:{segmentation_key}:{window_start.isoformat()}"
        redis = await get_redis()
        is_new = await check_idempotency_key(redis, idempotency_key, ttl_seconds=900)
        if not is_new:
            return

        observations = await fetch_observations(
            endpoint_id=endpoint_id,
            segmentation_key=segmentation_key,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            limit=1000,
        )

        if not observations:
            return

        feature_vector = extract_features(observations, window_start, window_end)

        features_only = {
            "response_level": feature_vector.response_level.model_dump(),
            "fields": {k: v.model_dump() for k, v in feature_vector.fields.items()},
        }
        features_json = json.dumps(features_only)

        baseline_row = await fetch_active_baseline(endpoint_id, segmentation_key)

        if not baseline_row:
            await insert_feature_vector_and_drift_score(
                endpoint_id=endpoint_id,
                segmentation_key=segmentation_key,
                fv_window_start=window_start.isoformat(),
                fv_window_end=window_end.isoformat(),
                fv_sample_count=feature_vector.sample_count,
                fv_features_json=features_json,
                fv_model_version="1.0.0",
                drift_score=0.0,
                drift_components_json="[]",
                drift_alert_triggered=False,
                drift_model_version="1.0.0",
            )
            return

        baseline = self._parse_baseline(baseline_row)
        baseline_time_val = baseline_row.get("time")
        baseline_snapshot_time = baseline_time_val.isoformat() if baseline_time_val else None

        drift_result = score_drift(current=feature_vector, baseline=baseline)

        maturity = resolve_maturity_state(baseline.sample_count)

        deployment_recency_hours: float | None = None
        endpoint_row = await fetch_endpoint_by_id(endpoint_id)
        if endpoint_row:
            project_id = endpoint_row.get("project_id")
            if project_id:
                deploy_row = await fetch_recent_deployment(str(project_id))
                if deploy_row:
                    deployed_at = deploy_row.get("deployed_at")
                    if isinstance(deployed_at, datetime):
                        if deployed_at.tzinfo is None:
                            deployed_at = deployed_at.replace(tzinfo=UTC)
                        deployment_recency_hours = (now - deployed_at).total_seconds() / 3600.0

        baseline_age_hours = 0.0
        if isinstance(baseline_time_val, datetime):
            bt = baseline_time_val
            if bt.tzinfo is None:
                bt = bt.replace(tzinfo=UTC)
            baseline_age_hours = (now - bt).total_seconds() / 3600.0

        persistence_key = f"{PERSISTENCE_KEY_PREFIX}:{endpoint_id}:{segmentation_key}"
        anomaly_persistence_windows = 0
        try:
            persist_val = await redis.get(persistence_key)
            anomaly_persistence_windows = int(persist_val) if persist_val else 0
        except (TypeError, ValueError):
            anomaly_persistence_windows = 0

        confidence = compute_confidence(
            maturity_state=maturity,
            sample_count=baseline.sample_count,
            baseline_age_hours=baseline_age_hours,
            window_days=baseline.window_days,
            deployment_recency_hours=deployment_recency_hours,
            anomaly_persistence_windows=anomaly_persistence_windows,
            baseline_time=baseline_time_val if isinstance(baseline_time_val, datetime) else None,
        )

        if drift_result.total_score >= PERSISTENCE_INCREMENT_THRESHOLD:
            await redis.incr(persistence_key)
            await redis.expire(persistence_key, PERSISTENCE_TTL_S)
        elif drift_result.total_score < PERSISTENCE_RESET_THRESHOLD:
            await redis.delete(persistence_key)

        alert_triggered = should_alert(drift_result.total_score, confidence)
        components_json = json.dumps([c.model_dump() for c in drift_result.components])

        await insert_feature_vector_and_drift_score(
            endpoint_id=endpoint_id,
            segmentation_key=segmentation_key,
            fv_window_start=window_start.isoformat(),
            fv_window_end=window_end.isoformat(),
            fv_sample_count=feature_vector.sample_count,
            fv_features_json=features_json,
            fv_model_version="1.0.0",
            drift_score=drift_result.total_score,
            drift_components_json=components_json,
            drift_alert_triggered=alert_triggered,
            drift_model_version=drift_result.model_version,
            baseline_snapshot_time=baseline_snapshot_time,
        )

        if alert_triggered:
            summary = generate_alert_summary(drift_result)
            org_id = msg_data.get("org_id", "")
            project_id_str = msg_data.get("project_id", "")
            drift_event: dict[Any, Any] = {
                "endpoint_id": endpoint_id,
                "segmentation_key": segmentation_key,
                "org_id": org_id,
                "project_id": project_id_str,
                "drift_score": str(drift_result.total_score),
                "confidence_score": str(confidence.score),
                "confidence_state": confidence.level.value,
                "severity": drift_result.severity.value if drift_result.severity else "low",
                "alert_type": drift_result.alert_type or "behavioral_drift",
                "model_version": drift_result.model_version,
                "timestamp": now.isoformat(),
                "baseline_snapshot_time": baseline_snapshot_time or "",
                "summary": summary,
                "components": json.dumps([c.model_dump() for c in drift_result.components]),
            }
            await redis.xadd(DRIFT_STREAM_KEY, drift_event, maxlen=100000)

            logger.info(
                "drift_detected",
                endpoint_id=endpoint_id,
                score=drift_result.total_score,
                severity=drift_result.severity.value if drift_result.severity else None,
                confidence=confidence.level.value,
                alert_type=drift_result.alert_type,
            )

    def _parse_baseline(self, row: dict) -> BaselineData:
        baseline_json = row.get("baseline")
        if isinstance(baseline_json, str):
            baseline_data = json.loads(baseline_json)
        else:
            baseline_data = baseline_json or {}

        baseline_time = row.get("time")

        return BaselineData(
            sample_count=row.get("sample_count", 0),
            window_days=row.get("window_days", 7),
            baseline_time=baseline_time,
            **baseline_data,
        )

    async def _baseline_consume_loop(self) -> None:
        while self._running:
            try:
                await self._consume_baseline_requests()
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("baseline_consume_error", error=str(exc))
                await asyncio.sleep(2.0)

    async def _consume_baseline_requests(self) -> None:
        redis = await get_redis()

        messages = await redis.xreadgroup(
            BASELINE_CONSUMER_GROUP,
            self._consumer_name,
            {BASELINE_REQUEST_KEY: ">"},
            count=10,
            block=BLOCK_MS,
        )

        if not messages:
            return

        for stream_name, stream_messages in messages:
            for msg_id, msg_data in stream_messages:
                try:
                    await self._handle_baseline_request(msg_data)
                    await redis.xack(BASELINE_REQUEST_KEY, BASELINE_CONSUMER_GROUP, msg_id)
                except Exception as exc:
                    logger.error(
                        "baseline_request_failed",
                        msg_id=msg_id,
                        error=str(exc),
                    )

    async def _handle_baseline_request(self, data: dict[str, str]) -> None:
        endpoint_id = data.get("endpoint_id", "")
        segmentation_key = data.get("segmentation_key", "default")

        if not endpoint_id:
            return

        current_baseline = await fetch_active_baseline(endpoint_id, segmentation_key)
        current_window = current_baseline.get("window_days", 7) if current_baseline else 7

        fv_rows = await fetch_feature_vectors_for_baseline(
            endpoint_id=endpoint_id,
            segmentation_key=segmentation_key,
            window_days=current_window,
        )

        if not fv_rows:
            return

        feature_vectors: list[FeatureVectorData] = []
        for row in fv_rows:
            features_data = row.get("features", {})
            if isinstance(features_data, str):
                features_data = json.loads(features_data)

            rl_data = features_data.get("response_level", {})
            fields_data = features_data.get("fields", {})

            rl = ResponseLevelFeatures(**rl_data) if rl_data else ResponseLevelFeatures()
            fields = {k: FieldFeatures(**v) for k, v in fields_data.items()} if fields_data else {}

            ws = row.get("window_start", row.get("time"))
            we = row.get("window_end", row.get("time"))

            fv = FeatureVectorData(
                window_start=ws,
                window_end=we,
                sample_count=row.get("sample_count", 0),
                response_level=rl,
                fields=fields,
            )
            feature_vectors.append(fv)

        baseline = compute_baseline(feature_vectors)

        baseline_dict = {
            "response_level": baseline.response_level.model_dump(),
            "fields": {k: v.model_dump() for k, v in baseline.fields.items()},
        }
        baseline_json = json.dumps(baseline_dict)

        maturity = resolve_maturity_state(baseline.sample_count)

        confidence = compute_confidence(
            maturity_state=maturity,
            sample_count=baseline.sample_count,
            baseline_age_hours=0.0,
            window_days=baseline.window_days,
        )

        await insert_baseline_snapshot(
            endpoint_id=endpoint_id,
            segmentation_key=segmentation_key,
            window_days=baseline.window_days,
            sample_count=baseline.sample_count,
            baseline_json=baseline_json,
            confidence_score=confidence.score,
            maturity_state=maturity.value,
        )

        await update_endpoint_maturity(
            endpoint_id=endpoint_id,
            maturity_state=maturity.value,
            observation_count=baseline.sample_count,
        )

        logger.info(
            "baseline_recomputed",
            endpoint_id=endpoint_id,
            segmentation_key=segmentation_key,
            sample_count=baseline.sample_count,
            maturity_state=maturity.value,
            confidence_score=confidence.score,
        )


async def run_worker() -> None:
    worker = StreamWorker()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(worker.stop()))
    loop.add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(worker.stop()))

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
