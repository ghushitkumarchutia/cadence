"""
Hypothesis-based property tests for mathematical invariants in the intelligence module.
"""
from __future__ import annotations
import math
import numpy as np
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.divergence import (
    jensen_shannon_divergence, kl_divergence, population_stability_index,
    proportion_z_test, rate_z_score, safe_pct_change, shannon_entropy, laplace_smooth,
)
from app.core.baseline_computer import _compute_ewma_weights, resolve_maturity_state
from app.core.confidence_scorer import compute_confidence
from app.core.drift_scorer import score_drift
from app.schemas.features import FeatureVectorData, LatencyStats, ResponseLevelFeatures
from app.schemas.scoring import BaselineData, MaturityState

def dist_st(mn=1, mx=10):
    return st.dictionaries(
        keys=st.text(min_size=1, max_size=5, alphabet="abcde"),
        values=st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=mn, max_size=mx,
    )

class TestJSDProperties:
    @given(p=dist_st(), q=dist_st())
    @settings(max_examples=200, deadline=None)
    def test_range(self, p, q):
        r = jensen_shannon_divergence(p, q)
        assert 0.0 <= r <= 1.0

    @given(p=dist_st(), q=dist_st())
    @settings(max_examples=200, deadline=None)
    def test_symmetry(self, p, q):
        assert abs(jensen_shannon_divergence(p, q) - jensen_shannon_divergence(q, p)) < 1e-10

    @given(p=dist_st())
    @settings(max_examples=100, deadline=None)
    def test_self_zero(self, p):
        assert jensen_shannon_divergence(p, p) < 1e-8

    def test_empty(self):
        assert jensen_shannon_divergence({}, {}) == 0.0

class TestKLProperties:
    @given(p=dist_st(), q=dist_st())
    @settings(max_examples=200, deadline=None)
    def test_non_negative(self, p, q):
        assert kl_divergence(p, q) >= -1e-10

    @given(p=dist_st())
    @settings(max_examples=100, deadline=None)
    def test_self_zero(self, p):
        assert abs(kl_divergence(p, p)) < 1e-8

class TestPSIProperties:
    @given(p=dist_st(), q=dist_st())
    @settings(max_examples=200, deadline=None)
    def test_non_negative(self, p, q):
        assert population_stability_index(p, q) >= -1e-10

    @given(p=dist_st())
    @settings(max_examples=100, deadline=None)
    def test_self_zero(self, p):
        assert abs(population_stability_index(p, p)) < 1e-8

class TestEWMAProperties:
    @given(n=st.integers(min_value=1, max_value=500))
    @settings(max_examples=100, deadline=None)
    def test_sum_to_one(self, n):
        w = _compute_ewma_weights(n)
        assert abs(w.sum() - 1.0) < 1e-10

    @given(n=st.integers(min_value=2, max_value=500))
    @settings(max_examples=100, deadline=None)
    def test_monotonic(self, n):
        w = _compute_ewma_weights(n)
        assert w[-1] >= w[0]

    @given(n=st.integers(min_value=1, max_value=500))
    @settings(max_examples=100, deadline=None)
    def test_all_positive(self, n):
        assert np.all(_compute_ewma_weights(n) > 0)

class TestDriftScoreProperties:
    def _fv(self, m=100.0, s=10.0):
        from datetime import UTC, datetime
        return FeatureVectorData(
            window_start=datetime.now(UTC), window_end=datetime.now(UTC), sample_count=100,
            response_level=ResponseLevelFeatures(latency=LatencyStats(p50=m, p95=m*1.5, p99=m*2, mean=m, std=s)),
        )
    def _bl(self, m=100.0, s=10.0):
        return BaselineData(
            response_level=ResponseLevelFeatures(latency=LatencyStats(p50=m, p95=m*1.5, p99=m*2, mean=m, std=s)),
            sample_count=1000, window_days=7,
        )

    @given(
        m=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        s=st.floats(min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, deadline=None)
    def test_range(self, m, s):
        r = score_drift(self._fv(m*2, s), self._bl(m, s))
        assert 0.0 <= r.total_score <= 10.0

    def test_identical_zero(self):
        r = score_drift(self._fv(100, 10), self._bl(100, 10))
        assert r.total_score < 0.5

    def test_empty_baseline_zero(self):
        r = score_drift(self._fv(200, 10), BaselineData(sample_count=0, window_days=0))
        assert r.total_score == 0.0

class TestConfidenceProperties:
    @given(
        sc=st.integers(min_value=0, max_value=100000),
        age=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        wd=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=200, deadline=None)
    def test_range(self, sc, age, wd):
        r = compute_confidence(MaturityState.STABILIZING, sc, age, wd)
        assert 0.0 <= r.score <= 1.0

class TestProportionZProperties:
    def test_identical_zero(self):
        assert abs(proportion_z_test(0.5, 0.5, 1000)) < 1e-10

    def test_zero_sample_zero(self):
        assert proportion_z_test(0.5, 0.3, 0) == 0.0

class TestSafePctChangeProperties:
    def test_both_zero(self):
        assert safe_pct_change(0.0, 0.0) == 0.0

    def test_baseline_zero(self):
        assert safe_pct_change(5.0, 0.0) == 100.0

    @given(
        o=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
        b=st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200, deadline=None)
    def test_finite(self, o, b):
        assert math.isfinite(safe_pct_change(o, b))

class TestShannonEntropyProperties:
    def test_empty(self):
        assert shannon_entropy([]) == 0.0

    def test_single_value(self):
        assert shannon_entropy(["a", "a", "a"]) == 0.0

    @given(v=st.lists(st.text(min_size=1, max_size=3, alphabet="abc"), min_size=1, max_size=100))
    @settings(max_examples=100, deadline=None)
    def test_non_negative(self, v):
        assert shannon_entropy(v) >= 0.0

class TestMaturityProperties:
    def test_ranges(self):
        assert resolve_maturity_state(0) == MaturityState.INITIALIZING
        assert resolve_maturity_state(99) == MaturityState.INITIALIZING
        assert resolve_maturity_state(100) == MaturityState.LEARNING
        assert resolve_maturity_state(999) == MaturityState.LEARNING
        assert resolve_maturity_state(1000) == MaturityState.STABILIZING
        assert resolve_maturity_state(4999) == MaturityState.STABILIZING
        assert resolve_maturity_state(5000) == MaturityState.PRODUCTION_TRUSTED

    def test_sparse(self):
        assert resolve_maturity_state(5000, daily_observation_rate=50) == MaturityState.SPARSE_TRAFFIC

    @given(s=st.integers(min_value=0, max_value=1000000))
    @settings(max_examples=100, deadline=None)
    def test_always_valid(self, s):
        assert resolve_maturity_state(s) in list(MaturityState)
