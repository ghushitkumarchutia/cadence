from __future__ import annotations

import math
from collections import Counter

import numpy as np
from scipy.spatial.distance import jensenshannon as _scipy_jsd

LAPLACE_EPSILON = 1e-3
PSI_STABLE = 0.1
PSI_MODERATE = 0.25


def laplace_smooth(
    counts: dict[str, float],
    all_keys: set[str],
    epsilon: float = LAPLACE_EPSILON,
) -> dict[str, float]:
    total = sum(counts.values()) + epsilon * len(all_keys)
    if total <= 0:
        uniform = 1.0 / max(len(all_keys), 1)
        return {k: uniform for k in all_keys}
    return {k: (counts.get(k, 0.0) + epsilon) / total for k in all_keys}


def jensen_shannon_divergence(
    p_dist: dict[str, float],
    q_dist: dict[str, float],
) -> float:
    all_keys = set(p_dist.keys()) | set(q_dist.keys())
    if not all_keys:
        return 0.0

    p_smooth = laplace_smooth(p_dist, all_keys)
    q_smooth = laplace_smooth(q_dist, all_keys)

    sorted_keys = sorted(all_keys)
    p = np.array([p_smooth[k] for k in sorted_keys], dtype=np.float64)
    q = np.array([q_smooth[k] for k in sorted_keys], dtype=np.float64)

    p_sum = p.sum()
    q_sum = q.sum()
    if p_sum > 0:
        p = p / p_sum
    if q_sum > 0:
        q = q / q_sum

    js_distance = _scipy_jsd(p, q, base=2.0)

    if not np.isfinite(js_distance):
        return 0.0

    jsd = float(js_distance ** 2)
    return max(0.0, min(1.0, jsd))


def kl_divergence(
    p_dist: dict[str, float],
    q_dist: dict[str, float],
) -> float:
    all_keys = set(p_dist.keys()) | set(q_dist.keys())
    if not all_keys:
        return 0.0

    p_smooth = laplace_smooth(p_dist, all_keys)
    q_smooth = laplace_smooth(q_dist, all_keys)

    p = np.array([p_smooth[k] for k in sorted(all_keys)], dtype=np.float64)
    q = np.array([q_smooth[k] for k in sorted(all_keys)], dtype=np.float64)

    mask = (p > 0) & (q > 0)
    if not np.any(mask):
        return 0.0

    return float(np.sum(np.where(mask, p * np.log2(p / q), 0.0)))


def population_stability_index(
    baseline_dist: dict[str, float],
    current_dist: dict[str, float],
) -> float:
    all_keys = set(baseline_dist.keys()) | set(current_dist.keys())
    if not all_keys:
        return 0.0

    bl_smooth = laplace_smooth(baseline_dist, all_keys)
    cr_smooth = laplace_smooth(current_dist, all_keys)

    psi = 0.0
    for k in all_keys:
        expected = bl_smooth[k]
        actual = cr_smooth[k]
        if expected > 0 and actual > 0:
            psi += (actual - expected) * math.log(actual / expected)

    return max(0.0, psi)


def proportion_z_test(
    observed_rate: float,
    baseline_rate: float,
    sample_count: int,
) -> float:
    if sample_count <= 0:
        return 0.0

    p = max(min(baseline_rate, 0.9999), 0.0001)
    se = math.sqrt(p * (1.0 - p) / sample_count)

    if se < 1e-10:
        if abs(observed_rate - baseline_rate) < 1e-10:
            return 0.0
        return 5.0 if observed_rate > baseline_rate else -5.0

    return (observed_rate - baseline_rate) / se


def rate_z_score(
    observed: float,
    baseline_mean: float,
    baseline_std: float,
) -> float:
    if baseline_std < 1e-10:
        if abs(observed - baseline_mean) < 1e-10:
            return 0.0
        return 5.0 if observed > baseline_mean else -5.0

    return (observed - baseline_mean) / baseline_std


def safe_pct_change(observed: float, baseline: float) -> float:
    if abs(baseline) < 1e-10:
        return 0.0 if abs(observed) < 1e-10 else 100.0
    return ((observed - baseline) / abs(baseline)) * 100.0


def shannon_entropy(values: list[str]) -> float:
    if not values:
        return 0.0
    counter = Counter(values)
    total = len(values)
    entropy = 0.0
    for count in counter.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy
