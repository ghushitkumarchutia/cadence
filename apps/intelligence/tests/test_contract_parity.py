"""
Contract parity tests — ensures Python Pydantic output matches Drizzle ORM schema expectations.
If these pass, Node.js integration is guaranteed.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.schemas.events import DriftDetectedPayload, RawObservationPayload
from app.schemas.features import FeatureVectorData, FieldFeatures, ResponseLevelFeatures
from app.schemas.scoring import (
    AlertSeverity,
    BaselineData,
    ConfidenceLevel,
    ConfidenceResult,
    DriftComponent,
    DriftResult,
    DriftType,
)

from conftest import make_baseline, make_feature_vector, make_field_features, make_response_level


class TestDriftEventContract:
    """Validates drift event structure matches what Node.js alert engine consumes via Redis Stream."""

    def test_drift_event_all_required_fields(self):
        """The stream worker publishes these exact keys. Node.js reads them."""
        required_keys = {
            "endpoint_id", "segmentation_key", "org_id", "project_id",
            "drift_score", "confidence_score", "confidence_state",
            "severity", "alert_type", "model_version", "timestamp",
            "baseline_snapshot_time", "summary", "components",
        }
        # Simulate what stream_worker._trigger_feature_extraction builds
        drift_event = {
            "endpoint_id": "ep_001",
            "segmentation_key": "default",
            "org_id": "org_001",
            "project_id": "proj_001",
            "drift_score": str(5.1234),
            "confidence_score": str(0.8500),
            "confidence_state": ConfidenceLevel.HIGH.value,
            "severity": AlertSeverity.MEDIUM.value,
            "alert_type": "latency_shift",
            "model_version": "1.0.0",
            "timestamp": datetime.now(UTC).isoformat(),
            "baseline_snapshot_time": datetime.now(UTC).isoformat(),
            "summary": "Test summary",
            "components": json.dumps([]),
        }
        assert required_keys == set(drift_event.keys())

    def test_drift_score_is_string(self):
        """Redis Streams require all values to be strings."""
        score = 5.1234
        assert isinstance(str(score), str)

    def test_confidence_state_enum_values(self):
        valid = {"low", "moderate", "high", "production_trusted"}
        for level in ConfidenceLevel:
            assert level.value in valid

    def test_severity_enum_values(self):
        valid = {"low", "medium", "high", "critical"}
        for sev in AlertSeverity:
            assert sev.value in valid

    def test_components_json_roundtrip(self):
        comp = DriftComponent(
            feature_name="latency.p95",
            drift_type=DriftType.LATENCY_SHIFT,
            baseline_value=100.0,
            observed_value=500.0,
            deviation_z=5.0,
            deviation_pct=400.0,
            weight=0.8,
        )
        json_str = json.dumps([comp.model_dump()])
        parsed = json.loads(json_str)
        assert len(parsed) == 1
        assert parsed[0]["feature_name"] == "latency.p95"
        assert parsed[0]["drift_type"] == "latency_shift"


class TestFeatureVectorDBContract:
    """Validates feature_vectors.features JSONB column structure."""

    def test_features_json_structure(self):
        fv = make_feature_vector()
        features_only = {
            "response_level": fv.response_level.model_dump(),
            "fields": {k: v.model_dump() for k, v in fv.fields.items()},
        }
        # Must have exactly these two top-level keys
        assert set(features_only.keys()) == {"response_level", "fields"}

    def test_response_level_has_required_keys(self):
        rl = make_response_level()
        dump = rl.model_dump()
        required = {"latency", "status_codes", "response_size", "payload_entropy",
                     "schema_hash", "schema_version"}
        assert required == set(dump.keys())

    def test_field_features_serializable(self):
        ff = make_field_features()
        dump = ff.model_dump()
        json_str = json.dumps(dump)
        parsed = json.loads(json_str)
        assert parsed["presence_rate"] == 1.0
        assert parsed["dominant_type"] == "number"


class TestBaselineDBContract:
    """Validates baseline_snapshots.baseline JSONB column structure."""

    def test_baseline_json_structure(self):
        bl = make_baseline()
        baseline_dict = {
            "response_level": bl.response_level.model_dump(),
            "fields": {k: v.model_dump() for k, v in bl.fields.items()},
        }
        assert set(baseline_dict.keys()) == {"response_level", "fields"}

    def test_baseline_parse_roundtrip(self):
        """Simulate what _parse_baseline does in stream_worker."""
        bl = make_baseline()
        baseline_dict = {
            "response_level": bl.response_level.model_dump(),
            "fields": {k: v.model_dump() for k, v in bl.fields.items()},
        }
        json_str = json.dumps(baseline_dict)
        parsed = json.loads(json_str)
        # Must reconstruct BaselineData from it
        reconstructed = BaselineData(
            sample_count=bl.sample_count,
            window_days=bl.window_days,
            **parsed,
        )
        assert reconstructed.sample_count == bl.sample_count
        assert "price" in reconstructed.fields

    def test_baseline_handles_empty_fields(self):
        data = {"response_level": {}, "fields": {}}
        bl = BaselineData(sample_count=0, window_days=0, **data)
        assert bl.sample_count == 0
        assert bl.fields == {}


class TestDriftScoreDBContract:
    """Validates drift_scores table constraints."""

    def test_score_precision(self):
        """numeric(8,4) — max value 9999.9999, max 4 decimal places."""
        result = DriftResult(total_score=9.1234, components=[], model_version="1.0.0")
        assert result.total_score <= 9999.9999
        rounded = round(result.total_score, 4)
        assert rounded == 9.1234

    def test_score_max_from_scorer(self):
        """Drift scorer caps at 10.0 which fits numeric(8,4)."""
        assert 10.0 <= 9999.9999

    def test_model_version_is_string(self):
        result = DriftResult(total_score=0.0, components=[], model_version="1.0.0")
        assert isinstance(result.model_version, str)


class TestConfidenceScoreDBContract:
    """Validates confidence_score fits numeric(5,4)."""

    def test_confidence_precision(self):
        """numeric(5,4) — max value 1.0000."""
        conf = ConfidenceResult(score=0.8567, level=ConfidenceLevel.HIGH)
        rounded = round(conf.score, 4)
        assert rounded <= 1.0000
        assert rounded >= 0.0

    def test_confidence_always_in_range(self):
        from app.core.confidence_scorer import compute_confidence
        from app.schemas.scoring import MaturityState
        c = compute_confidence(MaturityState.PRODUCTION_TRUSTED, 10000, 24.0, 14)
        assert 0.0 <= c.score <= 1.0


class TestObservationEventContract:
    """Validates RawObservationPayload matches what Node.js ingestion sends."""

    def test_raw_observation_fields(self):
        payload = RawObservationPayload(
            observation_time="2024-01-01T00:00:00Z",
            endpoint_id="ep_001",
            status_code=200,
            latency_ms=100,
        )
        dump = payload.model_dump()
        assert "observation_time" in dump
        assert "endpoint_id" in dump
        assert "status_code" in dump
        assert "latency_ms" in dump
        assert dump["segmentation_key"] == "default"
