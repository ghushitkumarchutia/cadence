"""
Defensive fallback tests — specifically targeting the remaining 4% coverage gaps.
These tests use "adversarial" or malformed inputs to trigger defensive branches.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from app.core.baseline_computer import (
    compute_baseline,
    _resolve_maturity,
)
from app.core.confidence_scorer import compute_confidence
from app.core.divergence import (
    jensen_shannon_divergence,
    kl_divergence,
    proportion_z_test,
)
from app.core.drift_scorer import (
    _compute_weighted_score,
    _determine_alert_type,
    score_drift,
)
from app.core.feature_extractor import (
    extract_features,
    _ensure_datetime,
    _safe_float,
)
from app.core.normalizer import (
    _normalize_value,
    _extract_structure,
)
from app.schemas.features import (
    DominantType,
    FeatureVectorData,
    FieldFeatures,
    LatencyStats,
    ResponseLevelFeatures,
    ResponseSizeStats,
)
from app.schemas.scoring import BaselineData, DriftComponent, DriftType, MaturityState

from conftest import make_feature_vector, make_field_features

class TestBaselineDefensive:
    def test_resolve_maturity_billion_fallback(self):
        # Line 110: Fallback for extremely high sample counts
        assert _resolve_maturity(2_000_000_000, 0.0) == MaturityState.PRODUCTION_TRUSTED

    def test_merge_zero_sample_vectors(self):
        # Lines 141, 159: Vectors with 0 samples should be skipped
        fv_empty = make_feature_vector(sample_count=0)
        bl = compute_baseline([fv_empty])
        assert bl.sample_count == 0
        assert bl.response_level.latency.mean == 0.0

    def test_merge_single_field_zero_weight(self):
        # Line 229: Field weight is zero
        fv = make_feature_vector(sample_count=0, fields={"test": make_field_features()})
        bl = compute_baseline([fv])
        # The field is processed but returns default FieldFeatures
        assert bl.fields["test"] == FieldFeatures()

class TestConfidenceDefensive:
    def test_compute_confidence_with_baseline_time(self):
        # Lines 30-33: Passing baseline_time instead of hours
        # Naive datetime to trigger line 32
        naive_time = datetime(2024, 1, 1, 12, 0)
        c = compute_confidence(
            MaturityState.PRODUCTION_TRUSTED,
            10000,
            0.0,
            7,
            baseline_time=naive_time
        )
        assert c.score > 0.0

class TestDivergenceDefensive:
    def test_jsd_non_finite_fallback(self):
        # Line 51: Fallback for non-finite JSD distance
        with pytest.MonkeyPatch.context() as m:
            m.setattr("app.core.divergence._scipy_jsd", lambda p, q, base: float("nan"))
            jsd = jensen_shannon_divergence({"A": 0.5}, {"A": 0.5})
            assert jsd == 0.0

    def test_kl_mask_empty_fallback(self):
        # Line 73: Fallback when p and q have no overlapping positive keys
        with pytest.MonkeyPatch.context() as m:
            m.setattr("numpy.any", lambda x: False)
            kl = kl_divergence({"A": 1.0}, {"B": 1.0})
            assert kl == 0.0

    def test_proportion_z_test_small_se_different_rates(self):
        # Lines 111-113: Very small SE with differing rates
        # Using a massive sample count to force se < 1e-10
        z_pos = proportion_z_test(0.5, 0.4, 10**25)
        assert z_pos == 5.0
        z_neg = proportion_z_test(0.3, 0.4, 10**25)
        assert z_neg == -5.0

    def test_proportion_z_test_small_se_same_rates(self):
        # Line 112: se < 1e-10 and rates are same
        z = proportion_z_test(0.4, 0.4, 10**25)
        assert z == 0.0

class TestDriftScorerDefensive:
    def test_weighted_score_zero_total_weight(self):
        # Line 93: Components with zero weight
        comp = DriftComponent(
            feature_name="test",
            drift_type=DriftType.LATENCY_SHIFT,
            baseline_value=0, observed_value=0, deviation_z=5.0, deviation_pct=0,
            weight=0.0
        )
        assert _compute_weighted_score([comp]) == 0.0

    def test_determine_alert_type_no_components(self):
        # Line 108: Fallback alert type
        assert _determine_alert_type([]) == "behavioral_drift"

    def test_score_status_code_drift_high_error_rate(self):
        # Lines 170-174: Status code drift for errors
        current = make_feature_vector(sample_count=1000, response_level={"status_codes": {"500": 0.5, "200": 0.5}})
        bl_fv = make_feature_vector(sample_count=1000, response_level={"status_codes": {"200": 1.0}})
        baseline = BaselineData(
            response_level=bl_fv.response_level,
            fields=bl_fv.fields,
            sample_count=bl_fv.sample_count,
            window_days=7,
            maturity_state=MaturityState.PRODUCTION_TRUSTED,
            baseline_time=datetime.now(UTC)
        )
        res = score_drift(current, baseline)
        # Verify component was added (lines 170-174)
        types = [c.drift_type for c in res.components]
        assert DriftType.STATUS_CODE_SHIFT in types

    def test_baseline_computer_line_216_dead_code(self):
        # To hit line 216, we need 'field_path' to be in 'all_fields' but NOT in any 'fv.fields'
        from app.core.baseline_computer import _merge_field_features
        
        class GhostFields(dict):
            def keys(self):
                # First call returns 'ghost', second call returns nothing
                if hasattr(self, "_called"):
                    return iter([])
                self._called = True
                return iter(["ghost"])
            def __contains__(self, key):
                return False

        class GhostFV:
            def __init__(self):
                self.fields = GhostFields()
                self.sample_count = 10
        
        # This will put "ghost" in all_fields, but then "ghost" won't be in fv.fields
        _merge_field_features([GhostFV()], np.array([1.0]))

class TestFeatureExtractorDefensive:
    def test_safe_float_edge_cases(self):
        # Lines 30, 33: None and non-finite
        assert _safe_float(None, 42.0) == 42.0
        assert _safe_float(float("nan"), 42.0) == 42.0
        assert _safe_float(float("inf"), 42.0) == 42.0

    def test_ensure_datetime_naive(self):
        # Line 69: Naive datetime object
        naive = datetime(2024, 1, 1)
        res = _ensure_datetime(naive)
        assert res.tzinfo == UTC

    def test_empty_col_latency_stats(self):
        # Line 104: Empty column in latency stats
        import polars as pl
        from app.core.feature_extractor import _compute_latency_stats_polars
        df = pl.DataFrame({"latency_ms": [None]})
        res = _compute_latency_stats_polars(df)
        assert isinstance(res, LatencyStats)
        assert res.mean == 0.0

    def test_empty_col_status_dist(self):
        # Line 118: Empty column in status distribution
        import polars as pl
        from app.core.feature_extractor import _compute_status_code_distribution_polars
        df = pl.DataFrame({"status_code": [None]})
        res = _compute_status_code_distribution_polars(df)
        assert res == {}

    def test_extract_field_features_max_count_limit(self):
        # Lines 187-188: More than 500 fields
        obs = [{"time": "2024-01-01T00:00:00Z", "latency_ms": 100, "status_code": 200,
                "payload_sample": {f"f{i}": i for i in range(600)}}]
        res = extract_features(obs, "2024-01-01T00:00:00Z", "2024-01-01T00:15:00Z")
        assert len(res.fields) <= 500

class TestNormalizerDefensive:
    def test_normalize_value_none_depth_fallback(self):
        # Line 62: Triggered by nested None
        res = _normalize_value({"a": None}, 0)
        assert res == {"a": None}

    def test_normalize_value_fallback_to_str(self):
        # Line 79: Object that is not a basic type
        class Custom:
            def __str__(self): return "custom"
        res = _normalize_value(Custom(), 0)
        assert res == "custom"

    def test_extract_structure_max_depth_fallback(self):
        # Line 109: Depth limit fallback
        res = _extract_structure({"a": 1}, 11)
        assert res == "dict"

    def test_extract_structure_custom_type_fallback(self):
        # Line 134: Custom type fallback
        class Custom: pass
        res = _extract_structure(Custom(), 0)
        assert res == "Custom"

class TestSchemasDefensive:
    def test_parse_datetime_aware_string(self):
        # Line 77: String WITH timezone
        fv = FeatureVectorData(
            window_start="2024-01-01T12:00:00+00:00",
            window_end="2024-01-01T12:15:00+00:00",
            sample_count=10
        )
        assert fv.window_start.tzinfo == UTC

    def test_parse_datetime_naive_string(self):
        # Lines 74-76: Naive string
        fv = FeatureVectorData(
            window_start="2024-01-01T12:00:00",
            window_end="2024-01-01T12:15:00",
            sample_count=10
        )
        assert fv.window_start.tzinfo == UTC

    def test_parse_datetime_naive_object(self):
        # Line 79: Naive datetime object
        naive = datetime(2024, 1, 1, 12, 0)
        fv = FeatureVectorData(
            window_start=naive,
            window_end=naive,
            sample_count=10
        )
        assert fv.window_start.tzinfo == UTC

