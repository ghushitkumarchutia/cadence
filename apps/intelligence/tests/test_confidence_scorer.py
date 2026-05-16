"""
Aggressive tests for app.core.confidence_scorer — every bracket, every boundary, should_alert truth table.
"""
from __future__ import annotations

import pytest

from app.core.confidence_scorer import (
    _deployment_score,
    _freshness_score,
    _maturity_score,
    _sample_score,
    _score_to_level,
    compute_confidence,
    should_alert,
)
from app.schemas.scoring import ConfidenceLevel, ConfidenceResult, MaturityState


class TestComputeConfidence:
    def test_initializing_low(self):
        c = compute_confidence(MaturityState.INITIALIZING, 10, 0.0, 7)
        assert c.level == ConfidenceLevel.LOW

    def test_learning_moderate(self):
        c = compute_confidence(MaturityState.LEARNING, 500, 2.0, 7)
        assert c.level in (ConfidenceLevel.LOW, ConfidenceLevel.MODERATE)

    def test_stabilizing(self):
        c = compute_confidence(MaturityState.STABILIZING, 3000, 12.0, 7)
        assert c.score > 0.4

    def test_production_trusted_high(self):
        c = compute_confidence(MaturityState.PRODUCTION_TRUSTED, 10000, 24.0, 14)
        assert c.level in (ConfidenceLevel.HIGH, ConfidenceLevel.PRODUCTION_TRUSTED)
        assert c.score > 0.7

    def test_sparse_traffic_low(self):
        c = compute_confidence(MaturityState.SPARSE_TRAFFIC, 50, 48.0, 30)
        assert c.score < 0.5

    def test_persistence_boost(self):
        base = compute_confidence(MaturityState.LEARNING, 500, 2.0, 7, anomaly_persistence_windows=0)
        boosted = compute_confidence(MaturityState.LEARNING, 500, 2.0, 7, anomaly_persistence_windows=3)
        assert boosted.score > base.score

    def test_persistence_boost_cap(self):
        c = compute_confidence(MaturityState.PRODUCTION_TRUSTED, 10000, 24.0, 14,
                               anomaly_persistence_windows=20)
        assert c.score <= 1.0

    def test_deployment_penalty(self):
        c_recent = compute_confidence(MaturityState.PRODUCTION_TRUSTED, 10000, 24.0, 14,
                                      deployment_recency_hours=0.3)
        c_old = compute_confidence(MaturityState.PRODUCTION_TRUSTED, 10000, 24.0, 14,
                                   deployment_recency_hours=72.0)
        assert c_recent.score < c_old.score

    def test_factors_present(self):
        c = compute_confidence(MaturityState.PRODUCTION_TRUSTED, 10000, 24.0, 14)
        assert "maturity" in c.factors
        assert "sample_size" in c.factors
        assert "freshness" in c.factors
        assert "deployment" in c.factors


class TestMaturityScore:
    def test_initializing(self):
        assert _maturity_score(MaturityState.INITIALIZING) == 0.1

    def test_learning(self):
        assert _maturity_score(MaturityState.LEARNING) == 0.35

    def test_stabilizing(self):
        assert _maturity_score(MaturityState.STABILIZING) == 0.65

    def test_production_trusted(self):
        assert _maturity_score(MaturityState.PRODUCTION_TRUSTED) == 1.0

    def test_sparse_traffic(self):
        assert _maturity_score(MaturityState.SPARSE_TRAFFIC) == 0.3


class TestSampleScore:
    def test_under_50(self):
        assert _sample_score(10) == 0.05

    def test_50(self):
        assert _sample_score(50) == 0.15

    def test_100(self):
        assert _sample_score(100) == 0.3

    def test_500(self):
        assert _sample_score(500) == 0.5

    def test_1000(self):
        assert _sample_score(1000) == 0.7

    def test_5000(self):
        assert _sample_score(5000) == 0.9

    def test_10000(self):
        assert _sample_score(10000) == 1.0


class TestFreshnessScore:
    def test_zero_window(self):
        assert _freshness_score(1.0, 0) == 0.1

    def test_very_fresh(self):
        # 7-day window, age=12h → ratio=12/168=0.071 → 1.0
        assert _freshness_score(12.0, 7) == 1.0

    def test_quarter_stale(self):
        # ratio = 42/168 = 0.25 → 1.0
        assert _freshness_score(42.0, 7) == 1.0

    def test_half_stale(self):
        # ratio = 84/168 = 0.5 → 0.8
        assert _freshness_score(84.0, 7) == 0.8

    def test_three_quarter_stale(self):
        # ratio = 126/168 = 0.75 → 0.5
        assert _freshness_score(126.0, 7) == 0.5

    def test_fully_stale(self):
        # ratio = 168/168 = 1.0 → 0.3
        assert _freshness_score(168.0, 7) == 0.3

    def test_over_stale(self):
        assert _freshness_score(300.0, 7) == 0.1


class TestDeploymentScore:
    def test_none(self):
        assert _deployment_score(None) == 1.0

    def test_very_recent(self):
        assert _deployment_score(0.3) == 0.2

    def test_recent(self):
        assert _deployment_score(1.0) == 0.5

    def test_moderate(self):
        assert _deployment_score(4.0) == 0.8

    def test_old(self):
        assert _deployment_score(8.0) == 1.0


class TestScoreToLevel:
    def test_below_040(self):
        assert _score_to_level(0.39) == ConfidenceLevel.LOW

    def test_at_040(self):
        assert _score_to_level(0.40) == ConfidenceLevel.MODERATE

    def test_below_065(self):
        assert _score_to_level(0.64) == ConfidenceLevel.MODERATE

    def test_at_065(self):
        assert _score_to_level(0.65) == ConfidenceLevel.HIGH

    def test_below_085(self):
        assert _score_to_level(0.84) == ConfidenceLevel.HIGH

    def test_at_085(self):
        assert _score_to_level(0.85) == ConfidenceLevel.PRODUCTION_TRUSTED


class TestShouldAlert:
    """Full truth table for should_alert."""

    def _conf(self, level: ConfidenceLevel) -> ConfidenceResult:
        return ConfidenceResult(score=0.5, level=level)

    # CRITICAL: score >= 8.0 always alerts regardless of confidence
    def test_critical_always_alerts_low(self):
        assert should_alert(9.0, self._conf(ConfidenceLevel.LOW)) is True

    def test_critical_always_alerts_at_boundary(self):
        assert should_alert(8.0, self._conf(ConfidenceLevel.LOW)) is True

    # HIGH: score >= 6.0 needs MODERATE+
    def test_high_with_low_no_alert(self):
        assert should_alert(7.0, self._conf(ConfidenceLevel.LOW)) is False

    def test_high_with_moderate_alerts(self):
        assert should_alert(7.0, self._conf(ConfidenceLevel.MODERATE)) is True

    def test_high_at_boundary(self):
        assert should_alert(6.0, self._conf(ConfidenceLevel.MODERATE)) is True

    # MEDIUM: score >= 4.0 needs HIGH+
    def test_medium_with_moderate_no_alert(self):
        assert should_alert(5.0, self._conf(ConfidenceLevel.MODERATE)) is False

    def test_medium_with_high_alerts(self):
        assert should_alert(5.0, self._conf(ConfidenceLevel.HIGH)) is True

    def test_medium_at_boundary(self):
        assert should_alert(4.0, self._conf(ConfidenceLevel.HIGH)) is True

    # LOW: score >= 2.0 needs PRODUCTION_TRUSTED
    def test_low_with_high_no_alert(self):
        assert should_alert(3.0, self._conf(ConfidenceLevel.HIGH)) is False

    def test_low_with_production_trusted_alerts(self):
        assert should_alert(3.0, self._conf(ConfidenceLevel.PRODUCTION_TRUSTED)) is True

    def test_low_at_boundary(self):
        assert should_alert(2.0, self._conf(ConfidenceLevel.PRODUCTION_TRUSTED)) is True

    # Below all thresholds
    def test_below_all_thresholds(self):
        assert should_alert(1.5, self._conf(ConfidenceLevel.PRODUCTION_TRUSTED)) is False

    def test_zero_score(self):
        assert should_alert(0.0, self._conf(ConfidenceLevel.PRODUCTION_TRUSTED)) is False
