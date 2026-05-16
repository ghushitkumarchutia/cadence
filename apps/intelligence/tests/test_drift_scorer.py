"""
Aggressive tests for app.core.drift_scorer — every drift type, threshold boundary, weight correctness.
"""
from __future__ import annotations

import pytest

from app.core.drift_scorer import (
    _clamp_z,
    _compute_weighted_score,
    _map_severity,
    score_drift,
)
from app.schemas.features import DominantType
from app.schemas.scoring import (
    DRIFT_TYPE_WEIGHTS,
    AlertSeverity,
    DriftComponent,
    DriftType,
)

from conftest import make_baseline, make_feature_vector, make_field_features, make_response_level


class TestScoreDriftCore:
    def test_zero_baseline_returns_zero(self):
        current = make_feature_vector()
        baseline = make_baseline(sample_count=0)
        result = score_drift(current, baseline)
        assert result.total_score == 0.0
        assert result.components == []

    def test_identical_current_and_baseline_near_zero(self):
        rl = make_response_level()
        fields = {"price": make_field_features()}
        current = make_feature_vector(response_level=rl, fields=fields)
        baseline = make_baseline(response_level=rl, fields=fields)
        result = score_drift(current, baseline)
        assert result.total_score < 1.0

    def test_score_capped_at_ten(self):
        # Inject extreme deviations via latency
        current = make_feature_vector(
            response_level=make_response_level(
                latency={"p50": 10000.0, "p95": 20000.0, "p99": 30000.0, "mean": 15000.0, "std": 100.0}
            ),
        )
        baseline = make_baseline(
            response_level=make_response_level(
                latency={"p50": 100.0, "p95": 200.0, "p99": 300.0, "mean": 120.0, "std": 10.0}
            ),
        )
        result = score_drift(current, baseline)
        assert result.total_score <= 10.0

    def test_severity_none_below_2(self):
        assert _map_severity(1.5) is None

    def test_severity_low(self):
        assert _map_severity(3.0) == AlertSeverity.LOW

    def test_severity_medium(self):
        assert _map_severity(5.0) == AlertSeverity.MEDIUM

    def test_severity_high(self):
        assert _map_severity(7.0) == AlertSeverity.HIGH

    def test_severity_critical(self):
        assert _map_severity(9.0) == AlertSeverity.CRITICAL

    def test_severity_above_ten(self):
        assert _map_severity(10.5) == AlertSeverity.CRITICAL


class TestIndividualDriftTypes:
    def test_null_rate_spike(self):
        current = make_feature_vector(
            fields={"email": make_field_features(
                dominant_type=DominantType.STRING, mean=None, std=None,
                p25=None, p50=None, p75=None, p95=None, p99=None,
                min_val=None, max_val=None,
                null_rate=0.40, presence_rate=1.0, type_consistency=1.0,
                mean_length=10.0, std_length=2.0,
            )},
        )
        baseline = make_baseline(
            fields={"email": make_field_features(
                dominant_type=DominantType.STRING, mean=None, std=None,
                p25=None, p50=None, p75=None, p95=None, p99=None,
                min_val=None, max_val=None,
                null_rate=0.01, presence_rate=1.0, type_consistency=1.0,
                mean_length=10.0, std_length=2.0,
            )},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.NULL_RATE_SPIKE in types
        comp = next(c for c in result.components if c.drift_type == DriftType.NULL_RATE_SPIKE)
        assert comp.weight == DRIFT_TYPE_WEIGHTS[DriftType.NULL_RATE_SPIKE]

    def test_field_disappeared(self):
        current = make_feature_vector(fields={})
        baseline = make_baseline(
            fields={"important_field": make_field_features(presence_rate=0.95)},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.FIELD_DISAPPEARED in types
        comp = next(c for c in result.components if c.drift_type == DriftType.FIELD_DISAPPEARED)
        assert comp.weight == DRIFT_TYPE_WEIGHTS[DriftType.FIELD_DISAPPEARED]

    def test_numeric_distribution_shift(self):
        current = make_feature_vector(
            fields={"price": make_field_features(mean=200.0, std=10.0)},
        )
        baseline = make_baseline(
            fields={"price": make_field_features(mean=50.0, std=10.0)},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.NUMERIC_DISTRIBUTION_SHIFT in types

    def test_latency_shift(self):
        current = make_feature_vector(
            response_level=make_response_level(
                latency={"p50": 500.0, "p95": 800.0, "p99": 1000.0, "mean": 500.0, "std": 50.0},
            ),
        )
        baseline = make_baseline(
            response_level=make_response_level(
                latency={"p50": 100.0, "p95": 200.0, "p99": 300.0, "mean": 120.0, "std": 30.0},
            ),
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.LATENCY_SHIFT in types

    def test_response_size_shift(self):
        current = make_feature_vector(
            response_level=make_response_level(
                response_size={"mean": 5000.0, "std": 100.0, "p95": 6000.0},
            ),
        )
        baseline = make_baseline(
            response_level=make_response_level(
                response_size={"mean": 1024.0, "std": 100.0, "p95": 1200.0},
            ),
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.RESPONSE_SIZE_SHIFT in types

    def test_payload_entropy_drop(self):
        current = make_feature_vector(
            response_level=make_response_level(payload_entropy=1.0),
        )
        baseline = make_baseline(
            response_level=make_response_level(payload_entropy=5.0),
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.PAYLOAD_ENTROPY_DROP in types

    def test_type_consistency_drop(self):
        current = make_feature_vector(
            fields={"val": make_field_features(type_consistency=0.70)},
        )
        baseline = make_baseline(
            fields={"val": make_field_features(type_consistency=0.99)},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.TYPE_CONSISTENCY_DROP in types

    def test_schema_type_change(self):
        current = make_feature_vector(
            fields={"val": make_field_features(dominant_type=DominantType.STRING, type_consistency=0.9)},
        )
        baseline = make_baseline(
            fields={"val": make_field_features(dominant_type=DominantType.NUMBER, type_consistency=0.95)},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.SCHEMA_TYPE_CHANGE in types

    def test_presence_rate_drop(self):
        current = make_feature_vector(
            fields={"f": make_field_features(presence_rate=0.40)},
        )
        baseline = make_baseline(
            fields={"f": make_field_features(presence_rate=0.95)},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.PRESENCE_RATE_DROP in types

    def test_vocabulary_collapse(self):
        current = make_feature_vector(
            fields={"tag": make_field_features(
                dominant_type=DominantType.STRING, mean=None, std=None,
                p25=None, p50=None, p75=None, p95=None, p99=None,
                min_val=None, max_val=None,
                vocabulary_size=3, mean_length=5.0, std_length=1.0,
            )},
        )
        baseline = make_baseline(
            fields={"tag": make_field_features(
                dominant_type=DominantType.STRING, mean=None, std=None,
                p25=None, p50=None, p75=None, p95=None, p99=None,
                min_val=None, max_val=None,
                vocabulary_size=20, mean_length=5.0, std_length=1.0,
            )},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.VOCABULARY_COLLAPSE in types

    def test_structural_change_new_field(self):
        current = make_feature_vector(
            fields={
                "price": make_field_features(),
                "debug_flag": make_field_features(
                    dominant_type=DominantType.BOOLEAN, presence_rate=0.90,
                    mean=1.0, std=0.0,
                ),
            },
        )
        baseline = make_baseline(fields={"price": make_field_features()})
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.STRUCTURAL_CHANGE in types

    def test_schema_hash_change(self):
        current = make_feature_vector(
            response_level=make_response_level(schema_hash="new_hash_12345678"),
        )
        baseline = make_baseline(
            response_level=make_response_level(schema_hash="old_hash_87654321"),
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.STRUCTURAL_CHANGE in types

    def test_enum_distribution_drift(self):
        current = make_feature_vector(
            fields={"method": make_field_features(
                dominant_type=DominantType.STRING, mean=None, std=None,
                p25=None, p50=None, p75=None, p95=None, p99=None,
                min_val=None, max_val=None,
                mean_length=4.0, std_length=1.0,
                vocabulary_size=3, vocabulary_entropy=0.5,
                enum_distribution={"GET": 1.0, "POST": 0.0},
                enum_values=["GET", "POST"],
            )},
        )
        baseline = make_baseline(
            fields={"method": make_field_features(
                dominant_type=DominantType.STRING, mean=None, std=None,
                p25=None, p50=None, p75=None, p95=None, p99=None,
                min_val=None, max_val=None,
                mean_length=4.0, std_length=1.0,
                vocabulary_size=3, vocabulary_entropy=1.5,
                enum_distribution={"GET": 0.5, "POST": 0.5},
                enum_values=["GET", "POST"],
            )},
        )
        result = score_drift(current, baseline)
        types = [c.drift_type for c in result.components]
        assert DriftType.ENUM_COLLAPSE in types


class TestThresholdPrecision:
    def test_clamp_z_positive(self):
        assert _clamp_z(15.0) == 10.0

    def test_clamp_z_negative(self):
        assert _clamp_z(-15.0) == -10.0

    def test_clamp_z_within_bounds(self):
        assert _clamp_z(5.0) == 5.0

    def test_weighted_score_formula(self):
        comps = [
            DriftComponent(feature_name="a", drift_type=DriftType.LATENCY_SHIFT,
                           baseline_value=0, observed_value=0, deviation_z=4.0,
                           deviation_pct=0, weight=0.8),
            DriftComponent(feature_name="b", drift_type=DriftType.NULL_RATE_SPIKE,
                           baseline_value=0, observed_value=0, deviation_z=3.0,
                           deviation_pct=0, weight=1.5),
        ]
        score = _compute_weighted_score(comps)
        expected = (4.0 * 0.8 + 3.0 * 1.5) / (0.8 + 1.5)
        assert pytest.approx(score, abs=0.01) == expected
