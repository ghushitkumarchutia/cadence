from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.core.baseline_computer import resolve_maturity_state
from app.core.confidence_scorer import compute_confidence
from app.core.drift_scorer import score_drift
from app.schemas.scoring import (
    ScoreRequest,
    ScoreResponse,
)

router = APIRouter()


@router.post("/score", response_model=ScoreResponse)
async def score_endpoint(request: ScoreRequest) -> ScoreResponse:
    drift_result = score_drift(
        current=request.current_feature_vector,
        baseline=request.baseline_snapshot,
    )

    maturity = resolve_maturity_state(
        total_samples=request.baseline_snapshot.sample_count,
    )

    baseline_time = request.baseline_snapshot.baseline_time
    baseline_age_hours = 0.0
    if baseline_time is not None:
        now = datetime.now(UTC)
        if baseline_time.tzinfo is None:
            baseline_time = baseline_time.replace(tzinfo=UTC)
        baseline_age_hours = (now - baseline_time).total_seconds() / 3600.0

    confidence = compute_confidence(
        maturity_state=maturity,
        sample_count=request.baseline_snapshot.sample_count,
        baseline_age_hours=baseline_age_hours,
        window_days=request.baseline_snapshot.window_days,
        deployment_recency_hours=request.deployment_recency_hours,
        anomaly_persistence_windows=request.anomaly_persistence_windows,
        baseline_time=baseline_time,
    )

    return ScoreResponse(
        drift_result=drift_result,
        confidence=confidence,
    )
