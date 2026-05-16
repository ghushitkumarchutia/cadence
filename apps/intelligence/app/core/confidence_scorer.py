from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.scoring import (
    ConfidenceLevel,
    ConfidenceResult,
    MaturityState,
)

_MATURITY_WEIGHTS: dict[MaturityState, dict[str, float]] = {
    MaturityState.INITIALIZING: {"maturity": 0.50, "sample_size": 0.30, "freshness": 0.10, "deployment": 0.10},
    MaturityState.LEARNING: {"maturity": 0.45, "sample_size": 0.30, "freshness": 0.15, "deployment": 0.10},
    MaturityState.STABILIZING: {"maturity": 0.35, "sample_size": 0.30, "freshness": 0.20, "deployment": 0.15},
    MaturityState.PRODUCTION_TRUSTED: {"maturity": 0.25, "sample_size": 0.30, "freshness": 0.25, "deployment": 0.20},
    MaturityState.SPARSE_TRAFFIC: {"maturity": 0.50, "sample_size": 0.30, "freshness": 0.10, "deployment": 0.10},
}


def compute_confidence(
    maturity_state: MaturityState,
    sample_count: int,
    baseline_age_hours: float,
    window_days: int,
    deployment_recency_hours: float | None = None,
    anomaly_persistence_windows: int = 0,
    baseline_time: datetime | None = None,
) -> ConfidenceResult:
    if baseline_time is not None:
        now = datetime.now(UTC)
        if baseline_time.tzinfo is None:
            baseline_time = baseline_time.replace(tzinfo=UTC)
        baseline_age_hours = (now - baseline_time).total_seconds() / 3600.0

    maturity_score = _maturity_score(maturity_state)
    sample_score = _sample_score(sample_count)
    freshness_score = _freshness_score(baseline_age_hours, window_days)
    deployment_score = _deployment_score(deployment_recency_hours)

    weights = _MATURITY_WEIGHTS.get(maturity_state, _MATURITY_WEIGHTS[MaturityState.PRODUCTION_TRUSTED])

    composite = (
        maturity_score * weights["maturity"]
        + sample_score * weights["sample_size"]
        + freshness_score * weights["freshness"]
        + deployment_score * weights["deployment"]
    )

    if anomaly_persistence_windows > 0:
        persistence_boost = min(0.3, anomaly_persistence_windows * 0.05)
        composite = min(1.0, composite + persistence_boost)

    level = _score_to_level(composite)

    return ConfidenceResult(
        score=round(composite, 4),
        level=level,
        factors={
            "maturity": round(maturity_score, 4),
            "sample_size": round(sample_score, 4),
            "freshness": round(freshness_score, 4),
            "deployment": round(deployment_score, 4),
        },
    )


def should_alert(
    drift_score: float,
    confidence: ConfidenceResult,
) -> bool:
    if drift_score >= 8.0:
        return True

    if drift_score >= 6.0 and confidence.level in (
        ConfidenceLevel.MODERATE,
        ConfidenceLevel.HIGH,
        ConfidenceLevel.PRODUCTION_TRUSTED,
    ):
        return True

    if drift_score >= 4.0 and confidence.level in (
        ConfidenceLevel.HIGH,
        ConfidenceLevel.PRODUCTION_TRUSTED,
    ):
        return True

    if drift_score >= 2.0 and confidence.level == ConfidenceLevel.PRODUCTION_TRUSTED:
        return True

    return False


def _maturity_score(state: MaturityState) -> float:
    scores: dict[MaturityState, float] = {
        MaturityState.INITIALIZING: 0.1,
        MaturityState.LEARNING: 0.35,
        MaturityState.STABILIZING: 0.65,
        MaturityState.PRODUCTION_TRUSTED: 1.0,
        MaturityState.SPARSE_TRAFFIC: 0.3,
    }
    return scores.get(state, 0.1)


def _sample_score(sample_count: int) -> float:
    if sample_count >= 10000:
        return 1.0
    if sample_count >= 5000:
        return 0.9
    if sample_count >= 1000:
        return 0.7
    if sample_count >= 500:
        return 0.5
    if sample_count >= 100:
        return 0.3
    if sample_count >= 50:
        return 0.15
    return 0.05


def _freshness_score(baseline_age_hours: float, window_days: int) -> float:
    max_age_hours = window_days * 24.0
    if max_age_hours <= 0:
        return 0.1

    staleness_ratio = baseline_age_hours / max_age_hours
    if staleness_ratio <= 0.25:
        return 1.0
    if staleness_ratio <= 0.5:
        return 0.8
    if staleness_ratio <= 0.75:
        return 0.5
    if staleness_ratio <= 1.0:
        return 0.3
    return 0.1


def _deployment_score(deployment_recency_hours: float | None) -> float:
    if deployment_recency_hours is None:
        return 1.0

    if deployment_recency_hours < 0.5:
        return 0.2
    if deployment_recency_hours < 2.0:
        return 0.5
    if deployment_recency_hours < 6.0:
        return 0.8
    return 1.0


def _score_to_level(score: float) -> ConfidenceLevel:
    if score >= 0.85:
        return ConfidenceLevel.PRODUCTION_TRUSTED
    if score >= 0.65:
        return ConfidenceLevel.HIGH
    if score >= 0.40:
        return ConfidenceLevel.MODERATE
    return ConfidenceLevel.LOW
