from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.baseline_computer import resolve_maturity_state
from app.core.confidence_scorer import compute_confidence
from app.core.drift_scorer import score_drift
from app.core.feature_extractor import extract_features
from app.schemas.scoring import (
    ConfidenceResult,
    DriftResult,
    ReplayScoreRequest,
    ReplayScoreResponse,
)

router = APIRouter()

_REPLAY_WINDOW_SIZE = 100
_MAX_REPLAY_OBSERVATIONS = 10000


@router.post("/replay-score", response_model=ReplayScoreResponse)
async def replay_score(request: ReplayScoreRequest) -> ReplayScoreResponse:
    observations = request.observations
    max_obs = min(request.max_observations, _MAX_REPLAY_OBSERVATIONS)

    if len(observations) > max_obs:
        raise HTTPException(
            status_code=413,
            detail=f"Observation count {len(observations)} exceeds maximum {max_obs}",
        )

    baseline = request.baseline_snapshot
    results: list[DriftResult] = []
    confidences: list[ConfidenceResult] = []

    maturity = resolve_maturity_state(
        total_samples=baseline.sample_count,
    )

    baseline_time = baseline.baseline_time
    now = datetime.now(UTC)
    baseline_age_hours = 0.0
    if baseline_time is not None:
        if baseline_time.tzinfo is None:
            baseline_time = baseline_time.replace(tzinfo=UTC)
        baseline_age_hours = (now - baseline_time).total_seconds() / 3600.0

    for i in range(0, len(observations), _REPLAY_WINDOW_SIZE):
        window = observations[i : i + _REPLAY_WINDOW_SIZE]
        if not window:
            continue

        first_time = window[0].get("time") or now.isoformat()
        last_time = window[-1].get("time") or now.isoformat()

        fv = extract_features(window, first_time, last_time)
        drift_result = score_drift(current=fv, baseline=baseline)
        results.append(drift_result)

        confidence = compute_confidence(
            maturity_state=maturity,
            sample_count=baseline.sample_count,
            baseline_age_hours=baseline_age_hours,
            window_days=baseline.window_days,
            deployment_recency_hours=request.deployment_recency_hours,
            anomaly_persistence_windows=request.anomaly_persistence_windows,
            baseline_time=baseline_time,
        )
        confidences.append(confidence)

    total_alerts = sum(1 for r in results if r.severity is not None)
    avg_score = sum(r.total_score for r in results) / len(results) if results else 0.0
    max_score = max((r.total_score for r in results), default=0.0)

    summary: dict[str, Any] = {
        "total_windows": len(results),
        "total_alerts": total_alerts,
        "avg_drift_score": round(avg_score, 4),
        "max_drift_score": round(max_score, 4),
        "observations_processed": len(observations),
    }

    return ReplayScoreResponse(results=results, confidences=confidences, summary=summary)
