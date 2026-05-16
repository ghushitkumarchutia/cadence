from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.features import (
    FeatureVectorData,
    FieldFeatures,
    ResponseLevelFeatures,
)


class MaturityState(str, Enum):
    INITIALIZING = "initializing"
    LEARNING = "learning"
    STABILIZING = "stabilizing"
    PRODUCTION_TRUSTED = "production_trusted"
    SPARSE_TRAFFIC = "sparse_traffic"


class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    PRODUCTION_TRUSTED = "production_trusted"


class DriftType(str, Enum):
    NULL_RATE_SPIKE = "null_rate_spike"
    FIELD_DISAPPEARED = "field_disappeared"
    ENUM_COLLAPSE = "enum_collapse"
    NUMERIC_DISTRIBUTION_SHIFT = "numeric_distribution_shift"
    PAYLOAD_ENTROPY_DROP = "payload_entropy_drop"
    LATENCY_SHIFT = "latency_shift"
    RESPONSE_SIZE_SHIFT = "response_size_shift"
    TYPE_CONSISTENCY_DROP = "type_consistency_drop"
    VOCABULARY_COLLAPSE = "vocabulary_collapse"
    STATUS_CODE_SHIFT = "status_code_shift"
    STRUCTURAL_CHANGE = "structural_change"
    SCHEMA_TYPE_CHANGE = "schema_type_change"
    PRESENCE_RATE_DROP = "presence_rate_drop"


DRIFT_TYPE_WEIGHTS: dict[DriftType, float] = {
    DriftType.NULL_RATE_SPIKE: 1.5,
    DriftType.FIELD_DISAPPEARED: 2.0,
    DriftType.ENUM_COLLAPSE: 1.2,
    DriftType.NUMERIC_DISTRIBUTION_SHIFT: 1.0,
    DriftType.PAYLOAD_ENTROPY_DROP: 1.1,
    DriftType.LATENCY_SHIFT: 0.8,
    DriftType.RESPONSE_SIZE_SHIFT: 0.7,
    DriftType.TYPE_CONSISTENCY_DROP: 1.3,
    DriftType.VOCABULARY_COLLAPSE: 1.2,
    DriftType.STATUS_CODE_SHIFT: 1.0,
    DriftType.STRUCTURAL_CHANGE: 1.4,
    DriftType.SCHEMA_TYPE_CHANGE: 1.8,
    DriftType.PRESENCE_RATE_DROP: 1.3,
}


class DriftComponent(BaseModel):
    feature_name: str
    drift_type: DriftType
    baseline_value: float
    observed_value: float
    deviation_z: float
    deviation_pct: float
    weight: float


class DriftResult(BaseModel):
    total_score: float
    components: list[DriftComponent]
    model_version: str = "1.0.0"
    alert_type: str | None = None
    severity: AlertSeverity | None = None


class ConfidenceResult(BaseModel):
    score: float
    level: ConfidenceLevel
    factors: dict[str, float] = Field(default_factory=dict)


class BaselineData(BaseModel):
    response_level: ResponseLevelFeatures = Field(default_factory=ResponseLevelFeatures)
    fields: dict[str, FieldFeatures] = Field(default_factory=dict)
    sample_count: int = 0
    window_days: int = 7
    maturity_state: MaturityState | None = None
    baseline_time: datetime | None = None


class ScoreRequest(BaseModel):
    endpoint_id: str
    current_feature_vector: FeatureVectorData
    baseline_snapshot: BaselineData
    deployment_recency_hours: float | None = None
    anomaly_persistence_windows: int = 0


class ScoreResponse(BaseModel):
    drift_result: DriftResult
    confidence: ConfidenceResult


class ReplayScoreRequest(BaseModel):
    endpoint_id: str
    observations: list[dict[str, Any]]
    baseline_snapshot: BaselineData
    max_observations: int = 10000
    deployment_recency_hours: float | None = None
    anomaly_persistence_windows: int = 0


class ReplayScoreResponse(BaseModel):
    results: list[DriftResult]
    confidences: list[ConfidenceResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
