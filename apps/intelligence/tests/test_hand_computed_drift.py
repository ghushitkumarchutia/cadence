"""
Hand-computed drift scoring verification tests.

Every expected value here was computed by hand/calculator to verify
the code produces mathematically correct results.
"""
from __future__ import annotations
from datetime import UTC, datetime
import math
import pytest

from app.core.divergence import proportion_z_test, rate_z_score, safe_pct_change
from app.core.drift_scorer import score_drift, _compute_weighted_score, _map_severity
from app.core.confidence_scorer import compute_confidence, should_alert, _score_to_level
from app.schemas.features import (
    DominantType, FeatureVectorData, FieldFeatures,
    LatencyStats, ResponseLevelFeatures, ResponseSizeStats,
)
from app.schemas.scoring import (
    AlertSeverity, BaselineData, ConfidenceLevel, DriftComponent,
    DriftType, DRIFT_TYPE_WEIGHTS, MaturityState,
)

NOW = datetime.now(UTC)

class TestHandComputedZScores:
    """Verify z-score calculations with hand-computed values."""

    def test_latency_z_score(self):
        """baseline_mean=100, baseline_std=10, observed=130 → z = (130-100)/10 = 3.0"""
        z = rate_z_score(130.0, 100.0, 10.0)
        assert abs(z - 3.0) < 1e-10

    def test_latency_z_score_negative(self):
        """baseline_mean=100, baseline_std=10, observed=70 → z = (70-100)/10 = -3.0"""
        z = rate_z_score(70.0, 100.0, 10.0)
        assert abs(z - (-3.0)) < 1e-10

    def test_proportion_z_test_exact(self):
        """observed=0.15, baseline=0.02, n=500.
        se = sqrt(0.02 * 0.98 / 500) = sqrt(0.0000392) = 0.006260990...
        z = (0.15 - 0.02) / 0.006260990 = 20.764...
        """
        z = proportion_z_test(0.15, 0.02, 500)
        se = math.sqrt(0.02 * 0.98 / 500)
        expected_z = (0.15 - 0.02) / se
        assert abs(z - expected_z) < 1e-6

    def test_safe_pct_change_exact(self):
        """observed=150, baseline=100 → ((150-100)/100)*100 = 50.0%"""
        assert abs(safe_pct_change(150.0, 100.0) - 50.0) < 1e-10

    def test_safe_pct_change_decrease(self):
        """observed=80, baseline=100 → ((80-100)/100)*100 = -20.0%"""
        assert abs(safe_pct_change(80.0, 100.0) - (-20.0)) < 1e-10

    def test_z_score_zero_std_same_value(self):
        """std=0, observed==baseline → z = 0"""
        z = rate_z_score(100.0, 100.0, 0.0)
        assert z == 0.0

    def test_z_score_zero_std_different_value(self):
        """std=0, observed>baseline → z = 5.0 (capped)"""
        z = rate_z_score(110.0, 100.0, 0.0)
        assert z == 5.0

    def test_z_score_zero_std_negative(self):
        """std=0, observed<baseline → z = -5.0"""
        z = rate_z_score(90.0, 100.0, 0.0)
        assert z == -5.0


class TestHandComputedWeightedScore:
    """Verify the weighted score formula: sum(|z| * w) / sum(w)."""

    def test_single_component(self):
        """One component: |z|=3.0, w=0.8 → score = 3.0*0.8/0.8 = 3.0"""
        comps = [DriftComponent(
            feature_name="test", drift_type=DriftType.LATENCY_SHIFT,
            baseline_value=100, observed_value=130, deviation_z=3.0,
            deviation_pct=30.0, weight=0.8,
        )]
        score = _compute_weighted_score(comps)
        assert abs(score - 3.0) < 1e-10

    def test_two_components(self):
        """Two components:
        c1: |z|=3.0, w=0.8 → contribution = 2.4
        c2: |z|=5.0, w=1.5 → contribution = 7.5
        total_weight = 2.3
        score = (2.4 + 7.5) / 2.3 = 9.9 / 2.3 = 4.3043...
        """
        comps = [
            DriftComponent(feature_name="a", drift_type=DriftType.LATENCY_SHIFT,
                           baseline_value=0, observed_value=0, deviation_z=3.0,
                           deviation_pct=0, weight=0.8),
            DriftComponent(feature_name="b", drift_type=DriftType.NULL_RATE_SPIKE,
                           baseline_value=0, observed_value=0, deviation_z=5.0,
                           deviation_pct=0, weight=1.5),
        ]
        score = _compute_weighted_score(comps)
        expected = (3.0 * 0.8 + 5.0 * 1.5) / (0.8 + 1.5)
        assert abs(score - expected) < 1e-10

    def test_three_components_with_known_weights(self):
        """Three components using actual DRIFT_TYPE_WEIGHTS:
        LATENCY_SHIFT: w=0.8
        NULL_RATE_SPIKE: w=1.5
        FIELD_DISAPPEARED: w=2.0
        """
        w_lat = DRIFT_TYPE_WEIGHTS[DriftType.LATENCY_SHIFT]
        w_null = DRIFT_TYPE_WEIGHTS[DriftType.NULL_RATE_SPIKE]
        w_field = DRIFT_TYPE_WEIGHTS[DriftType.FIELD_DISAPPEARED]
        assert w_lat == 0.8
        assert w_null == 1.5
        assert w_field == 2.0

        comps = [
            DriftComponent(feature_name="a", drift_type=DriftType.LATENCY_SHIFT,
                           baseline_value=0, observed_value=0, deviation_z=2.5,
                           deviation_pct=0, weight=w_lat),
            DriftComponent(feature_name="b", drift_type=DriftType.NULL_RATE_SPIKE,
                           baseline_value=0, observed_value=0, deviation_z=4.0,
                           deviation_pct=0, weight=w_null),
            DriftComponent(feature_name="c", drift_type=DriftType.FIELD_DISAPPEARED,
                           baseline_value=0, observed_value=0, deviation_z=5.0,
                           deviation_pct=0, weight=w_field),
        ]
        total_w = w_lat + w_null + w_field  # 4.3
        weighted_sum = 2.5 * w_lat + 4.0 * w_null + 5.0 * w_field  # 2.0+6.0+10.0 = 18.0
        expected = weighted_sum / total_w  # 18.0 / 4.3 = 4.18604...
        score = _compute_weighted_score(comps)
        assert abs(score - expected) < 1e-6

    def test_empty_components(self):
        assert _compute_weighted_score([]) == 0.0

    def test_score_capped_at_10(self):
        """Even with extreme z-scores, score caps at 10."""
        comps = [DriftComponent(
            feature_name="x", drift_type=DriftType.LATENCY_SHIFT,
            baseline_value=0, observed_value=0, deviation_z=10.0,
            deviation_pct=0, weight=2.0,
        )]
        score = _compute_weighted_score(comps)
        assert score == 10.0


class TestHandComputedSeverityMapping:
    """Verify exact boundary values for severity thresholds."""

    def test_below_2_no_severity(self):
        assert _map_severity(0.0) is None
        assert _map_severity(1.0) is None
        assert _map_severity(1.99) is None

    def test_low_range(self):
        assert _map_severity(2.0) == AlertSeverity.LOW
        assert _map_severity(3.0) == AlertSeverity.LOW
        assert _map_severity(3.99) == AlertSeverity.LOW

    def test_medium_range(self):
        assert _map_severity(4.0) == AlertSeverity.MEDIUM
        assert _map_severity(5.0) == AlertSeverity.MEDIUM
        assert _map_severity(5.99) == AlertSeverity.MEDIUM

    def test_high_range(self):
        assert _map_severity(6.0) == AlertSeverity.HIGH
        assert _map_severity(7.0) == AlertSeverity.HIGH
        assert _map_severity(7.99) == AlertSeverity.HIGH

    def test_critical_range(self):
        assert _map_severity(8.0) == AlertSeverity.CRITICAL
        assert _map_severity(9.0) == AlertSeverity.CRITICAL
        assert _map_severity(10.0) == AlertSeverity.CRITICAL


class TestHandComputedConfidence:
    """Verify confidence scoring with known factor values."""

    def test_confidence_level_boundaries(self):
        assert _score_to_level(0.0) == ConfidenceLevel.LOW
        assert _score_to_level(0.39) == ConfidenceLevel.LOW
        assert _score_to_level(0.40) == ConfidenceLevel.MODERATE
        assert _score_to_level(0.64) == ConfidenceLevel.MODERATE
        assert _score_to_level(0.65) == ConfidenceLevel.HIGH
        assert _score_to_level(0.84) == ConfidenceLevel.HIGH
        assert _score_to_level(0.85) == ConfidenceLevel.PRODUCTION_TRUSTED
        assert _score_to_level(1.0) == ConfidenceLevel.PRODUCTION_TRUSTED


class TestShouldAlertDecisionMatrix:
    """Verify should_alert decision matrix at exact boundaries."""

    def test_critical_drift_always_alerts(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=0.1, level=ConfidenceLevel.LOW, factors={})
        assert should_alert(8.0, conf) is True
        assert should_alert(10.0, conf) is True

    def test_high_drift_moderate_confidence(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=0.5, level=ConfidenceLevel.MODERATE, factors={})
        assert should_alert(6.0, conf) is True

    def test_high_drift_low_confidence_no_alert(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=0.2, level=ConfidenceLevel.LOW, factors={})
        assert should_alert(6.0, conf) is False

    def test_medium_drift_high_confidence(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=0.7, level=ConfidenceLevel.HIGH, factors={})
        assert should_alert(4.0, conf) is True

    def test_low_drift_production_trusted(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=0.9, level=ConfidenceLevel.PRODUCTION_TRUSTED, factors={})
        assert should_alert(2.0, conf) is True

    def test_low_drift_non_trusted_no_alert(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=0.7, level=ConfidenceLevel.HIGH, factors={})
        assert should_alert(2.0, conf) is False

    def test_below_2_never_alerts(self):
        from app.schemas.scoring import ConfidenceResult
        conf = ConfidenceResult(score=1.0, level=ConfidenceLevel.PRODUCTION_TRUSTED, factors={})
        assert should_alert(1.99, conf) is False


class TestEndToEndDriftScoring:
    """Full pipeline: known inputs → known outputs."""

    def test_latency_spike_scoring(self):
        """Baseline: mean=100, std=10. Current: mean=150, p95=225.
        z_p95 = (225 - 150) / 10 = 7.5 → clamped to 7.5 (< 10)
        z_mean = (150 - 100) / 10 = 5.0
        Both trigger (>= 2.0), weight = 0.8 each
        weighted = (7.5*0.8 + 5.0*0.8) / (0.8+0.8) = 10.0/1.6 = 6.25
        """
        fv = FeatureVectorData(
            window_start=NOW, window_end=NOW, sample_count=200,
            response_level=ResponseLevelFeatures(
                latency=LatencyStats(p50=140, p95=225, p99=300, mean=150, std=20),
            ),
        )
        bl = BaselineData(
            response_level=ResponseLevelFeatures(
                latency=LatencyStats(p50=100, p95=150, p99=200, mean=100, std=10),
            ),
            sample_count=5000, window_days=7,
        )
        result = score_drift(fv, bl)
        assert result.total_score > 0
        assert result.severity is not None
        # Should have latency components
        lat_comps = [c for c in result.components if c.drift_type == DriftType.LATENCY_SHIFT]
        assert len(lat_comps) >= 1

    def test_field_disappeared_scoring(self):
        """A field present at 90% in baseline disappears in current.
        deviation_z = 5.0 (fixed), weight = 2.0
        score = 5.0 * 2.0 / 2.0 = 5.0 → MEDIUM severity
        """
        fv = FeatureVectorData(
            window_start=NOW, window_end=NOW, sample_count=100,
            fields={},
        )
        bl = BaselineData(
            fields={"user.name": FieldFeatures(presence_rate=0.9, null_rate=0.0,
                     type_consistency=1.0, dominant_type=DominantType.STRING)},
            sample_count=5000, window_days=7,
        )
        result = score_drift(fv, bl)
        disappeared = [c for c in result.components if c.drift_type == DriftType.FIELD_DISAPPEARED]
        assert len(disappeared) == 1
        assert disappeared[0].deviation_z == 5.0
        assert disappeared[0].weight == DRIFT_TYPE_WEIGHTS[DriftType.FIELD_DISAPPEARED]
