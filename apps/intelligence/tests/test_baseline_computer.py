"""
Aggressive tests for app.core.baseline_computer.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.core.baseline_computer import (
    EWMA_ALPHA,
    compute_baseline,
    is_post_deploy_window,
    resolve_maturity_state,
    should_recompute_baseline,
    _compute_ewma_weights,
)
from app.schemas.features import DominantType, FieldFeatures
from app.schemas.scoring import MaturityState

from conftest import make_feature_vector, make_field_features, make_response_level


class TestComputeBaseline:
    def test_empty_list(self):
        bl = compute_baseline([])
        assert bl.sample_count == 0
        assert bl.window_days == 0

    def test_single_feature_vector(self):
        fv = make_feature_vector(sample_count=500)
        bl = compute_baseline([fv])
        assert bl.sample_count == 500
        assert pytest.approx(bl.response_level.latency.mean, abs=0.1) == fv.response_level.latency.mean

    def test_two_vectors_ewma_weighted(self):
        fv1 = make_feature_vector(
            sample_count=100,
            response_level=make_response_level(
                latency={"p50": 100.0, "p95": 200.0, "p99": 300.0, "mean": 100.0, "std": 10.0}
            ),
        )
        fv2 = make_feature_vector(
            sample_count=100,
            response_level=make_response_level(
                latency={"p50": 200.0, "p95": 400.0, "p99": 600.0, "mean": 200.0, "std": 20.0}
            ),
        )
        bl = compute_baseline([fv1, fv2])
        assert bl.sample_count == 200
        assert bl.response_level.latency.mean > 100.0
        assert bl.response_level.latency.mean < 200.0

    def test_maturity_initializing(self):
        bl = compute_baseline([make_feature_vector(sample_count=50)])
        assert bl.maturity_state == MaturityState.INITIALIZING

    def test_maturity_learning(self):
        bl = compute_baseline([make_feature_vector(sample_count=500)])
        assert bl.maturity_state == MaturityState.LEARNING
        assert bl.window_days == 3

    def test_maturity_stabilizing(self):
        bl = compute_baseline([make_feature_vector(sample_count=3000)])
        assert bl.maturity_state == MaturityState.STABILIZING
        assert bl.window_days == 7

    def test_maturity_production_trusted(self):
        bl = compute_baseline([make_feature_vector(sample_count=6000)])
        assert bl.maturity_state == MaturityState.PRODUCTION_TRUSTED
        assert bl.window_days == 14

    def test_field_merging_across_vectors(self):
        fv1 = make_feature_vector(sample_count=100, fields={"price": make_field_features(mean=50.0)})
        fv2 = make_feature_vector(sample_count=100, fields={"quantity": make_field_features(mean=10.0)})
        bl = compute_baseline([fv1, fv2])
        assert "price" in bl.fields
        assert "quantity" in bl.fields

    def test_numeric_field_merging_weighted(self):
        fv1 = make_feature_vector(sample_count=100, fields={"p": make_field_features(mean=100.0)})
        fv2 = make_feature_vector(sample_count=100, fields={"p": make_field_features(mean=200.0)})
        bl = compute_baseline([fv1, fv2])
        assert 100.0 < bl.fields["p"].mean < 200.0

    def test_string_field_merging_vocabulary(self):
        sf1 = FieldFeatures(presence_rate=1.0, null_rate=0.0, type_consistency=1.0,
                            dominant_type=DominantType.STRING, mean_length=6.0, std_length=1.0,
                            vocabulary_size=5, vocabulary_entropy=2.0)
        sf2 = FieldFeatures(presence_rate=1.0, null_rate=0.0, type_consistency=1.0,
                            dominant_type=DominantType.STRING, mean_length=8.0, std_length=2.0,
                            vocabulary_size=10, vocabulary_entropy=3.0)
        fv1 = make_feature_vector(sample_count=100, fields={"s": sf1})
        fv2 = make_feature_vector(sample_count=100, fields={"s": sf2})
        bl = compute_baseline([fv1, fv2])
        assert bl.fields["s"].vocabulary_size == 10

    def test_status_code_accumulation(self):
        fv1 = make_feature_vector(sample_count=100,
                                  response_level=make_response_level(status_codes={"200": 1.0}))
        fv2 = make_feature_vector(sample_count=100,
                                  response_level=make_response_level(status_codes={"200": 0.5, "500": 0.5}))
        bl = compute_baseline([fv1, fv2])
        assert "200" in bl.response_level.status_codes
        assert 0.5 < bl.response_level.status_codes["200"] <= 1.0


class TestResolveMaturityState:
    def test_zero(self):
        assert resolve_maturity_state(0) == MaturityState.INITIALIZING

    def test_99(self):
        assert resolve_maturity_state(99) == MaturityState.INITIALIZING

    def test_100(self):
        assert resolve_maturity_state(100) == MaturityState.LEARNING

    def test_999(self):
        assert resolve_maturity_state(999) == MaturityState.LEARNING

    def test_1000(self):
        assert resolve_maturity_state(1000) == MaturityState.STABILIZING

    def test_5000(self):
        assert resolve_maturity_state(5000) == MaturityState.PRODUCTION_TRUSTED

    def test_sparse(self):
        assert resolve_maturity_state(10000, daily_observation_rate=50) == MaturityState.SPARSE_TRAFFIC


class TestShouldRecomputeBaseline:
    def test_zero_baseline_enough(self):
        assert should_recompute_baseline(10, 0) is True

    def test_zero_baseline_not_enough(self):
        assert should_recompute_baseline(9, 0) is False

    def test_ten_pct_increase(self):
        assert should_recompute_baseline(110, 100) is True

    def test_nine_pct_increase(self):
        assert should_recompute_baseline(109, 100) is False

    def test_age_exceeds_half_window(self):
        assert should_recompute_baseline(100, 100, baseline_age_hours=85.0, window_days=7) is True

    def test_fresh_small_increase(self):
        assert should_recompute_baseline(105, 100, baseline_age_hours=1.0, window_days=7) is False


class TestIsPostDeployWindow:
    def test_none(self):
        assert is_post_deploy_window(None) is False

    def test_recent(self):
        assert is_post_deploy_window(datetime.now(UTC) - timedelta(minutes=10)) is True

    def test_old(self):
        assert is_post_deploy_window(datetime.now(UTC) - timedelta(hours=2)) is False

    def test_naive_datetime(self):
        result = is_post_deploy_window(datetime.now() - timedelta(minutes=5))
        assert isinstance(result, bool)


class TestEWMAWeights:
    def test_single(self):
        w = _compute_ewma_weights(1)
        assert pytest.approx(w[0]) == 1.0

    def test_two_sum_to_one(self):
        w = _compute_ewma_weights(2)
        assert pytest.approx(np.sum(w)) == 1.0
        assert w[1] > w[0]

    def test_ten_sum_to_one_monotonic(self):
        w = _compute_ewma_weights(10)
        assert pytest.approx(np.sum(w)) == 1.0
        for i in range(1, len(w)):
            assert w[i] >= w[i - 1]
