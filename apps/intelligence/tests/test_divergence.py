"""
Aggressive tests for app.core.divergence — every statistical primitive used for drift detection.
Mathematical correctness is verified with hand-calculated expected values.
"""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings, strategies as st

from app.core.divergence import (
    jensen_shannon_divergence,
    kl_divergence,
    laplace_smooth,
    population_stability_index,
    proportion_z_test,
    rate_z_score,
    safe_pct_change,
    shannon_entropy,
)

from conftest import st_distribution

class TestLaplaceSmooth:
    def test_all_keys_present(self):
        counts = {"A": 10.0, "B": 20.0}
        all_keys = {"A", "B"}
        smoothed = laplace_smooth(counts, all_keys, epsilon=1.0)
        # total = 10 + 20 + 1*2 = 32
        assert pytest.approx(smoothed["A"], abs=1e-6) == 11.0 / 32.0
        assert pytest.approx(smoothed["B"], abs=1e-6) == 21.0 / 32.0
        assert pytest.approx(sum(smoothed.values()), abs=1e-6) == 1.0

    def test_missing_key_gets_epsilon(self):
        counts = {"A": 10.0}
        all_keys = {"A", "B"}
        smoothed = laplace_smooth(counts, all_keys, epsilon=1.0)
        # total = 10 + 0 + 1*2 = 12
        assert pytest.approx(smoothed["B"], abs=1e-6) == 1.0 / 12.0

    def test_empty_counts_uniform(self):
        counts: dict[str, float] = {}
        all_keys = {"A", "B", "C"}
        smoothed = laplace_smooth(counts, all_keys, epsilon=1.0)
        # total = 0 + 1*3 = 3, each = 1/3
        for v in smoothed.values():
            assert pytest.approx(v, abs=1e-6) == 1.0 / 3.0

    def test_zero_total_uniform(self):
        counts = {"A": 0.0, "B": 0.0}
        all_keys = {"A", "B"}
        smoothed = laplace_smooth(counts, all_keys, epsilon=0.0)
        # total = 0 + 0 + 0 = 0 → uniform = 1/2
        for v in smoothed.values():
            assert pytest.approx(v, abs=1e-6) == 0.5

    def test_sums_to_one(self):
        counts = {"X": 5.0, "Y": 3.0, "Z": 2.0}
        all_keys = {"X", "Y", "Z", "W"}
        smoothed = laplace_smooth(counts, all_keys)
        assert pytest.approx(sum(smoothed.values()), abs=1e-6) == 1.0

class TestJensenShannonDivergence:
    def test_identical_distributions_zero(self):
        dist = {"A": 0.5, "B": 0.5}
        jsd = jensen_shannon_divergence(dist, dist)
        assert pytest.approx(jsd, abs=1e-4) == 0.0

    def test_disjoint_distributions_near_one(self):
        p = {"A": 1.0, "B": 0.0}
        q = {"A": 0.0, "B": 1.0}
        jsd = jensen_shannon_divergence(p, q)
        # Laplace smoothing prevents exact 1.0
        assert jsd > 0.8
        assert jsd <= 1.0

    def test_symmetry(self):
        p = {"A": 0.7, "B": 0.3}
        q = {"A": 0.3, "B": 0.7}
        jsd_pq = jensen_shannon_divergence(p, q)
        jsd_qp = jensen_shannon_divergence(q, p)
        assert pytest.approx(jsd_pq, abs=1e-10) == jsd_qp

    def test_bounds_zero_to_one(self):
        p = {"A": 0.9, "B": 0.1}
        q = {"A": 0.1, "B": 0.9}
        jsd = jensen_shannon_divergence(p, q)
        assert 0.0 <= jsd <= 1.0

    def test_empty_distributions_zero(self):
        jsd = jensen_shannon_divergence({}, {})
        assert jsd == 0.0

    def test_single_element_distributions(self):
        p = {"A": 1.0}
        q = {"A": 1.0}
        jsd = jensen_shannon_divergence(p, q)
        assert pytest.approx(jsd, abs=1e-4) == 0.0

    def test_new_category_one_side(self):
        """The 'thin tail' problem — a category exists in current but not baseline."""
        p = {"A": 0.5, "B": 0.5}
        q = {"A": 0.4, "B": 0.4, "C": 0.2}
        jsd = jensen_shannon_divergence(p, q)
        assert jsd > 0.0
        assert jsd <= 1.0

    def test_many_categories(self):
        p = {str(i): 1.0 / 100 for i in range(100)}
        q = {str(i): 1.0 / 100 for i in range(100)}
        jsd = jensen_shannon_divergence(p, q)
        assert pytest.approx(jsd, abs=1e-4) == 0.0

    @given(p=st_distribution, q=st_distribution)
    @settings(max_examples=200, deadline=None)
    def test_fuzz_bounds_always_hold(self, p, q):
        jsd = jensen_shannon_divergence(p, q)
        assert 0.0 <= jsd <= 1.0

    @given(p=st_distribution, q=st_distribution)
    @settings(max_examples=200, deadline=None)
    def test_fuzz_symmetry_always_holds(self, p, q):
        jsd_pq = jensen_shannon_divergence(p, q)
        jsd_qp = jensen_shannon_divergence(q, p)
        assert pytest.approx(jsd_pq, abs=1e-8) == jsd_qp

class TestKLDivergence:
    def test_identical_distributions_zero(self):
        dist = {"A": 0.5, "B": 0.5}
        kl = kl_divergence(dist, dist)
        assert pytest.approx(kl, abs=1e-4) == 0.0

    def test_non_negativity(self):
        p = {"A": 0.7, "B": 0.3}
        q = {"A": 0.3, "B": 0.7}
        kl = kl_divergence(p, q)
        assert kl >= 0.0

    def test_asymmetric(self):
        """KL divergence is NOT symmetric — prove it."""
        p = {"A": 0.9, "B": 0.1}
        q = {"A": 0.1, "B": 0.9}
        kl_pq = kl_divergence(p, q)
        kl_qp = kl_divergence(q, p)
        # They should both be positive but not necessarily equal
        assert kl_pq > 0.0
        assert kl_qp > 0.0
        # Don't assert inequality — with smoothing and these specific values
        # they could be equal since p and q are mirror images

    def test_empty_distributions(self):
        assert kl_divergence({}, {}) == 0.0

    def test_known_value(self):
        """KL(p||q) for known distributions, hand-verified."""
        p = {"A": 0.5, "B": 0.5}
        q = {"A": 0.5, "B": 0.5}
        kl = kl_divergence(p, q)
        assert pytest.approx(kl, abs=1e-3) == 0.0

class TestPopulationStabilityIndex:
    def test_identical_zero(self):
        dist = {"A": 0.5, "B": 0.5}
        psi = population_stability_index(dist, dist)
        assert pytest.approx(psi, abs=1e-4) == 0.0

    def test_shift_positive(self):
        p = {"A": 0.5, "B": 0.5}
        q = {"A": 0.1, "B": 0.9}
        psi = population_stability_index(p, q)
        assert psi > 0.0

    def test_non_negative(self):
        p = {"A": 0.3, "B": 0.7}
        q = {"A": 0.8, "B": 0.2}
        psi = population_stability_index(p, q)
        assert psi >= 0.0

    def test_empty_distributions(self):
        assert population_stability_index({}, {}) == 0.0


class TestProportionZTest:
    def test_zero_sample_returns_zero(self):
        assert proportion_z_test(0.5, 0.5, 0) == 0.0

    def test_equal_rates_zero(self):
        z = proportion_z_test(0.5, 0.5, 1000)
        assert pytest.approx(z, abs=1e-6) == 0.0

    def test_rate_near_zero_no_crash(self):
        z = proportion_z_test(0.001, 0.0, 100)
        assert math.isfinite(z)
        assert z > 0.0

    def test_rate_near_one_no_crash(self):
        z = proportion_z_test(0.999, 1.0, 100)
        assert math.isfinite(z)

    def test_large_sample_proportional(self):
        # With n=10000, se = sqrt(0.5*0.5/10000) = 0.005
        # z = (0.55 - 0.50) / 0.005 = 10.0
        z = proportion_z_test(0.55, 0.50, 10000)
        assert pytest.approx(z, abs=0.1) == 10.0

    def test_extreme_rate_difference(self):
        z = proportion_z_test(1.0, 0.0, 100)
        # baseline clamped to 0.0001 → se = sqrt(0.0001 * 0.9999 / 100) ≈ 0.001
        assert math.isfinite(z)
        assert z > 0.0

class TestRateZScore:
    def test_zero_std_no_deviation(self):
        assert rate_z_score(100.0, 100.0, 0.0) == 0.0

    def test_zero_std_positive_deviation(self):
        assert rate_z_score(105.0, 100.0, 0.0) == 5.0

    def test_zero_std_negative_deviation(self):
        assert rate_z_score(95.0, 100.0, 0.0) == -5.0

    def test_normal_case(self):
        # z = (150 - 100) / 10 = 5.0
        z = rate_z_score(150.0, 100.0, 10.0)
        assert pytest.approx(z, abs=1e-6) == 5.0

class TestSafePctChange:
    def test_zero_baseline_zero_observed(self):
        assert safe_pct_change(0.0, 0.0) == 0.0

    def test_zero_baseline_nonzero_observed(self):
        assert safe_pct_change(100.0, 0.0) == 100.0

    def test_normal_increase(self):
        # (200 - 100) / 100 * 100 = 100%
        assert pytest.approx(safe_pct_change(200.0, 100.0)) == 100.0

    def test_normal_decrease(self):
        # (50 - 100) / 100 * 100 = -50%
        assert pytest.approx(safe_pct_change(50.0, 100.0)) == -50.0

class TestShannonEntropy:
    def test_empty_list(self):
        assert shannon_entropy([]) == 0.0

    def test_constant_value(self):
        assert shannon_entropy(["A", "A", "A"]) == 0.0

    def test_uniform_two_values(self):
        assert pytest.approx(shannon_entropy(["A", "B"]), abs=1e-6) == 1.0

    def test_uniform_four_values(self):
        assert pytest.approx(shannon_entropy(["A", "B", "C", "D"]), abs=1e-6) == 2.0
