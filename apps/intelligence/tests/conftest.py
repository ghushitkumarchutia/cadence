"""
Shared fixtures and factories for the Cadence Intelligence test suite.
All synthetic data is deterministic via fixed seeds.
"""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest
from hypothesis import strategies as st

from app.schemas.features import (
    DominantType,
    FeatureVectorData,
    FieldFeatures,
    LatencyStats,
    ResponseLevelFeatures,
    ResponseSizeStats,
)
from app.schemas.scoring import BaselineData, MaturityState


def make_observations(
    count: int,
    *,
    seed: int = 42,
    base_latency: float = 120.0,
    latency_std: float = 20.0,
    status_200_pct: float = 0.80,
    start_time: datetime | None = None,
    payload_template: dict[str, Any] | None = None,
    include_payload: bool = True,
) -> list[dict[str, Any]]:
    """Generate deterministic observations for testing."""
    rng = np.random.default_rng(seed)
    start = start_time or (datetime.now(UTC) - timedelta(days=7))

    user_pool = [
        {"id": f"usr_{i}", "email": f"user{i}@example.com"}
        for i in range(50)
    ]

    observations: list[dict[str, Any]] = []
    for i in range(count):
        t = start + timedelta(minutes=i)
        latency = max(1, int(rng.normal(base_latency, latency_std)))
        status_code = 200 if rng.random() < status_200_pct else 201

        obs: dict[str, Any] = {
            "time": t.isoformat(),
            "endpoint_id": "ep_test_001",
            "latency_ms": latency,
            "status_code": status_code,
            "response_size_bytes": 1024 + int(rng.normal(100, 20)),
            "segmentation_key": "default",
            "request_id": f"req_{i:06d}",
            "payload_hash": f"hash_{i % 100:04d}",
            "metadata": {},
        }

        if include_payload:
            if payload_template is not None:
                obs["payload_sample"] = copy.deepcopy(payload_template)
            else:
                user = user_pool[int(rng.integers(0, len(user_pool)))]
                obs["payload_sample"] = {
                    "user": copy.deepcopy(user),
                    "items": [
                        {"item_id": "item_1", "price": round(float(rng.uniform(5, 50)), 2)},
                        {"item_id": "item_2", "price": round(float(rng.uniform(10, 100)), 2)},
                    ],
                    "method": "GET" if rng.random() < 0.8 else "POST",
                    "active": bool(rng.random() < 0.9),
                }
        else:
            obs["payload_sample"] = None

        observations.append(obs)

    return observations

def make_latency_stats(**overrides: Any) -> LatencyStats:
    defaults = {"p50": 100.0, "p95": 200.0, "p99": 350.0, "mean": 120.0, "std": 30.0}
    defaults.update(overrides)
    return LatencyStats(**defaults)


def make_response_size_stats(**overrides: Any) -> ResponseSizeStats:
    defaults = {"mean": 1024.0, "std": 100.0, "p95": 1200.0}
    defaults.update(overrides)
    return ResponseSizeStats(**defaults)


def make_response_level(**overrides: Any) -> ResponseLevelFeatures:
    defaults: dict[str, Any] = {
        "latency": make_latency_stats(),
        "status_codes": {"200": 0.8, "201": 0.2},
        "response_size": make_response_size_stats(),
        "payload_entropy": 3.5,
        "schema_hash": "abcdef1234567890",
    }
    defaults.update(overrides)
    return ResponseLevelFeatures(**defaults)


def make_field_features(**overrides: Any) -> FieldFeatures:
    defaults: dict[str, Any] = {
        "presence_rate": 1.0,
        "null_rate": 0.0,
        "type_consistency": 1.0,
        "dominant_type": DominantType.NUMBER,
        "mean": 50.0,
        "std": 10.0,
        "p25": 40.0,
        "p50": 50.0,
        "p75": 60.0,
        "p95": 70.0,
        "p99": 80.0,
        "min_val": 10.0,
        "max_val": 90.0,
    }
    defaults.update(overrides)
    return FieldFeatures(**defaults)


def make_feature_vector(**overrides: Any) -> FeatureVectorData:
    now = datetime.now(UTC)
    defaults: dict[str, Any] = {
        "window_start": now - timedelta(minutes=15),
        "window_end": now,
        "sample_count": 100,
        "response_level": make_response_level(),
        "fields": {"price": make_field_features()},
    }
    defaults.update(overrides)
    return FeatureVectorData(**defaults)


def make_baseline(**overrides: Any) -> BaselineData:
    defaults: dict[str, Any] = {
        "response_level": make_response_level(),
        "fields": {"price": make_field_features()},
        "sample_count": 5000,
        "window_days": 7,
        "maturity_state": MaturityState.PRODUCTION_TRUSTED,
    }
    defaults.update(overrides)
    return BaselineData(**defaults)

st_json_primitive = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.sampled_from([float("nan"), float("inf"), float("-inf")]),
    st.booleans(),
    st.none(),
)

st_json = st.recursive(
    st_json_primitive,
    lambda children: st.one_of(
        st.lists(children, max_size=20),
        st.dictionaries(st.text(max_size=10), children, max_size=20),
    ),
    max_leaves=100,
)

st_observation = st.fixed_dictionaries({
    "time": st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
    ).map(lambda d: d.isoformat()),
    "latency_ms": st.integers(min_value=0, max_value=60000),
    "status_code": st.integers(min_value=100, max_value=599),
    "response_size_bytes": st.integers(min_value=0, max_value=10_000_000),
    "payload_sample": st_json,
    "payload_hash": st.text(max_size=32),
})

st_observations_list = st.lists(st_observation, min_size=1, max_size=100)

st_probability = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

st_distribution = st.dictionaries(
    st.text(min_size=1, max_size=5),
    st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=20,
).map(lambda d: {k: v / sum(d.values()) for k, v in d.items()})
