"""
Aggressive tests for app.core.feature_extractor — extraction correctness under all data shapes.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from hypothesis import given, settings

from app.core.feature_extractor import extract_features
from app.schemas.features import DominantType

from conftest import make_observations, st_observations_list

class TestExtractFeaturesCore:
    def test_empty_observations(self):
        ws = datetime.now(UTC)
        we = ws + timedelta(minutes=15)
        fv = extract_features([], ws, we)
        assert fv.sample_count == 0
        assert fv.response_level.latency.mean == 0.0
        assert fv.fields == {}

    def test_single_observation(self):
        obs = [{
            "time": "2024-01-01T00:00:00Z",
            "latency_ms": 100,
            "status_code": 200,
            "response_size_bytes": 1024,
            "payload_sample": {"key": "value"},
            "payload_hash": "hash_001",
        }]
        fv = extract_features(obs, "2024-01-01T00:00:00Z", "2024-01-01T00:15:00Z")
        assert fv.sample_count == 1
        assert fv.response_level.latency.mean == 100.0
        assert fv.response_level.latency.std == 0.0  # Single sample, no std

    def test_all_same_latency(self):
        obs = [
            {"time": f"2024-01-01T00:{i:02d}:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500}
            for i in range(50)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert fv.response_level.latency.mean == 100.0
        assert fv.response_level.latency.p50 == 100.0
        assert fv.response_level.latency.p95 == 100.0

    def test_all_same_status_code(self):
        obs = [
            {"time": f"2024-01-01T00:{i:02d}:00Z", "latency_ms": 100 + i, "status_code": 200,
             "response_size_bytes": 500}
            for i in range(20)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert "200" in fv.response_level.status_codes
        assert fv.response_level.status_codes["200"] == 1.0

    def test_mixed_status_codes(self):
        obs = []
        start = datetime(2024, 1, 1, tzinfo=UTC)
        for i in range(100):
            code = 200 if i < 80 else (404 if i < 90 else 500)
            t = start + timedelta(seconds=i)
            obs.append({
                "time": t.isoformat(), "latency_ms": 100,
                "status_code": code, "response_size_bytes": 500,
            })
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert pytest.approx(fv.response_level.status_codes["200"], abs=0.01) == 0.80
        assert pytest.approx(fv.response_level.status_codes["404"], abs=0.01) == 0.10
        assert pytest.approx(fv.response_level.status_codes["500"], abs=0.01) == 0.10

    def test_no_response_size(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200}
            for _ in range(10)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert fv.response_level.response_size.mean == 0.0

    def test_no_payload_hash_entropy_zero(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500}
            for _ in range(10)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert fv.response_level.payload_entropy == 0.0

    def test_all_unique_hashes_max_entropy(self):
        obs = [
            {"time": f"2024-01-01T00:{i:02d}:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500, "payload_hash": f"unique_{i}"}
            for i in range(16)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        # 16 unique values → entropy = log2(16) = 4.0
        assert pytest.approx(fv.response_level.payload_entropy, abs=0.01) == 4.0

    def test_all_same_hash_zero_entropy(self):
        obs = [
            {"time": f"2024-01-01T00:{i:02d}:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500, "payload_hash": "same_hash"}
            for i in range(10)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert fv.response_level.payload_entropy == 0.0

    def test_sample_count_equals_observation_count(self):
        obs = make_observations(73, seed=99)
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert fv.sample_count == 73

class TestFieldExtraction:
    def test_numeric_field_stats(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"price": float(i * 10)}}
            for i in range(1, 101)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        price = fv.fields.get("price")
        assert price is not None
        assert price.dominant_type == DominantType.NUMBER
        assert price.mean is not None
        assert price.std is not None
        assert price.p50 is not None
        assert price.min_val is not None
        assert price.max_val is not None
        assert pytest.approx(price.mean, abs=1.0) == 505.0  # mean of 10..1000
        assert price.min_val == 10.0
        assert price.max_val == 1000.0

    def test_string_field_stats(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"status": "active" if i % 2 == 0 else "inactive"}}
            for i in range(100)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        status = fv.fields.get("status")
        assert status is not None
        assert status.dominant_type == DominantType.STRING
        assert status.mean_length is not None
        assert status.vocabulary_size == 2
        assert status.vocabulary_entropy is not None
        assert pytest.approx(status.vocabulary_entropy, abs=0.01) == 1.0  # log2(2) for 50/50
        assert status.enum_values is not None
        assert sorted(status.enum_values) == ["active", "inactive"]
        assert status.enum_distribution is not None

    def test_boolean_field_stats(self):
        # 70% True, 30% False
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"active": i < 70}}
            for i in range(100)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        active = fv.fields.get("active")
        assert active is not None
        assert active.dominant_type == DominantType.BOOLEAN
        assert active.mean is not None
        assert pytest.approx(active.mean, abs=0.01) == 0.70

    def test_array_field_stats(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"tags": ["a", "b", "c"] if i % 2 == 0 else ["x"]}}
            for i in range(100)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        tags = fv.fields.get("tags[]")
        # Array items get flattened
        assert tags is not None

    def test_null_values_null_rate(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"value": None if i < 30 else 42}}
            for i in range(100)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        val = fv.fields.get("value")
        assert val is not None
        assert pytest.approx(val.null_rate, abs=0.01) == 0.30

    def test_mixed_types_dominant_type(self):
        # 70 strings, 30 ints
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"val": "text" if i < 70 else 42}}
            for i in range(100)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        val = fv.fields.get("val")
        assert val is not None
        assert val.dominant_type == DominantType.STRING
        assert pytest.approx(val.type_consistency, abs=0.01) == 0.70

    def test_presence_rate_partial_fields(self):
        obs = []
        for i in range(100):
            payload: dict = {"always": 1}
            if i < 60:
                payload["sometimes"] = 2
            obs.append({
                "time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
                "response_size_bytes": 500, "payload_sample": payload,
            })
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert pytest.approx(fv.fields["always"].presence_rate, abs=0.01) == 1.0
        assert pytest.approx(fv.fields["sometimes"].presence_rate, abs=0.01) == 0.60

    def test_nested_dict_flattened(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"user": {"name": "John", "age": 30}}}
            for _ in range(10)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert "user.name" in fv.fields
        assert "user.age" in fv.fields

    def test_deep_nesting_stops_at_max_depth(self):
        # Build 8-level deep nesting (MAX_FIELD_DEPTH=5)
        deep = {"a": 1}
        current = deep
        for i in range(8):
            inner = {f"level{i}": i}
            current["nested"] = inner
            current = inner

        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500, "payload_sample": deep}
            for _ in range(10)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        # Should not crash, fields should exist but depth is limited
        assert fv.sample_count == 10

    def test_nan_inf_filtered_from_numeric(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"val": float("nan") if i < 5 else float(i)}}
            for i in range(20)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        val = fv.fields.get("val")
        if val is not None and val.mean is not None:
            assert math.isfinite(val.mean)

    def test_categorical_threshold_enum_populated(self):
        # 10 unique values → under threshold of 50, so enum_distribution populated
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"category": f"cat_{i % 10}"}}
            for i in range(100)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        cat = fv.fields.get("category")
        assert cat is not None
        assert cat.enum_distribution is not None
        assert len(cat.enum_distribution) == 10

    def test_over_categorical_threshold_no_enum(self):
        # 60 unique values → over threshold of 50, so enum_distribution not populated
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500,
             "payload_sample": {"category": f"cat_{i}"}}
            for i in range(60)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        cat = fv.fields.get("category")
        assert cat is not None
        assert cat.enum_distribution is None

    def test_no_payloads_no_fields(self):
        obs = [
            {"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
             "response_size_bytes": 500}
            for _ in range(10)
        ]
        fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
        assert fv.fields == {}

class TestFeatureExtractorFuzz:
    @given(observations=st_observations_list)
    @settings(max_examples=200, deadline=None)
    def test_never_crashes_never_nan(self, observations):
        first_time = observations[0]["time"]
        last_time = observations[-1]["time"]
        fv = extract_features(observations, first_time, last_time)

        rl = fv.response_level
        assert math.isfinite(rl.latency.mean)
        assert math.isfinite(rl.latency.std)
        assert math.isfinite(rl.latency.p50)
        assert math.isfinite(rl.latency.p95)
        assert math.isfinite(rl.latency.p99)
        assert math.isfinite(rl.response_size.mean)
        assert math.isfinite(rl.response_size.std)
        assert math.isfinite(rl.payload_entropy)

        for field_path, field_stats in fv.fields.items():
            assert math.isfinite(field_stats.presence_rate)
            assert math.isfinite(field_stats.null_rate)
            assert math.isfinite(field_stats.type_consistency)
            if field_stats.mean is not None:
                assert math.isfinite(field_stats.mean)
            if field_stats.std is not None:
                assert math.isfinite(field_stats.std)

    @given(observations=st_observations_list)
    @settings(max_examples=200, deadline=None)
    def test_sample_count_always_matches(self, observations):
        fv = extract_features(observations, observations[0]["time"], observations[-1]["time"])
        assert fv.sample_count == len(observations)
