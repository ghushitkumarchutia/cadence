from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.scoring import AlertSeverity, ConfidenceLevel, DriftComponent


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    schema_version: str = "1.0.0"
    timestamp: str
    org_id: str
    project_id: str
    payload: dict[str, Any]


class RawObservationPayload(BaseModel):
    observation_time: str
    endpoint_id: str
    segmentation_key: str = "default"
    payload_hash: str | None = None
    status_code: int
    latency_ms: int
    request_id: str | None = None
    response_size_bytes: int | None = None
    region: str | None = None
    deployment_id: str | None = None
    org_id: str | None = None
    project_id: str | None = None


class FeatureVectorGeneratedPayload(BaseModel):
    feature_vector_time: str
    endpoint_id: str
    segmentation_key: str
    window_start: str
    window_end: str
    sample_count: int


class DriftDetectedPayload(BaseModel):
    endpoint_id: str
    segmentation_key: str
    drift_score: float
    components: list[DriftComponent]
    confidence_score: float
    confidence_state: ConfidenceLevel
    severity: AlertSeverity
    baseline_snapshot_time: str
    alert_type: str
    summary: str
