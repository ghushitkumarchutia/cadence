from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from app.schemas.features import (
    FeatureVectorData,
    FieldFeatures,
    LatencyStats,
    ResponseLevelFeatures,
    ResponseSizeStats,
)
from app.schemas.scoring import (
    BaselineData,
    MaturityState,
)

_MATURITY_THRESHOLDS: dict[MaturityState, tuple[int, int]] = {
    MaturityState.INITIALIZING: (0, 99),
    MaturityState.LEARNING: (100, 999),
    MaturityState.STABILIZING: (1000, 4999),
    MaturityState.PRODUCTION_TRUSTED: (5000, int(1e9)),
}

_WINDOW_DAYS: dict[MaturityState, int] = {
    MaturityState.INITIALIZING: 0,
    MaturityState.LEARNING: 3,
    MaturityState.STABILIZING: 7,
    MaturityState.PRODUCTION_TRUSTED: 14,
    MaturityState.SPARSE_TRAFFIC: 30,
}

EWMA_ALPHA = 0.1


def compute_baseline(
    feature_vectors: list[FeatureVectorData],
    daily_observation_rate: float = 0.0,
) -> BaselineData:
    if not feature_vectors:
        return BaselineData(sample_count=0, window_days=0)

    total_samples = sum(fv.sample_count for fv in feature_vectors)
    maturity = _resolve_maturity(total_samples, daily_observation_rate)
    window_days = _WINDOW_DAYS.get(maturity, 7)

    ewma_weights = _compute_ewma_weights(len(feature_vectors))
    response_level = _merge_response_level(feature_vectors, ewma_weights)
    fields = _merge_field_features(feature_vectors, ewma_weights)

    return BaselineData(
        response_level=response_level,
        fields=fields,
        sample_count=total_samples,
        window_days=window_days,
        maturity_state=maturity,
        baseline_time=datetime.now(UTC),
    )


def resolve_maturity_state(
    total_samples: int,
    daily_observation_rate: float = 0.0,
) -> MaturityState:
    return _resolve_maturity(total_samples, daily_observation_rate)


def should_recompute_baseline(
    current_sample_count: int,
    baseline_sample_count: int,
    baseline_age_hours: float = 0.0,
    window_days: int = 7,
) -> bool:
    if baseline_sample_count == 0:
        return current_sample_count >= 10

    max_age_hours = window_days * 24.0 * 0.5
    if max_age_hours > 0 and baseline_age_hours >= max_age_hours:
        return True

    increase_pct = (current_sample_count - baseline_sample_count) / baseline_sample_count
    return increase_pct >= 0.10


def is_post_deploy_window(
    deploy_time: datetime | None,
    grace_minutes: int = 30,
) -> bool:
    if deploy_time is None:
        return False
    now = datetime.now(UTC)
    if deploy_time.tzinfo is None:
        deploy_time = deploy_time.replace(tzinfo=UTC)
    elapsed = (now - deploy_time).total_seconds() / 60.0
    return elapsed < grace_minutes


def _resolve_maturity(
    total_samples: int,
    daily_rate: float,
) -> MaturityState:
    if daily_rate > 0 and daily_rate < 100:
        return MaturityState.SPARSE_TRAFFIC

    for state, (low, high) in _MATURITY_THRESHOLDS.items():
        if low <= total_samples <= high:
            return state

    return MaturityState.PRODUCTION_TRUSTED


def _compute_ewma_weights(n: int) -> np.ndarray:
    if n <= 1:
        return np.array([1.0], dtype=np.float64)

    raw = np.array([(1.0 - EWMA_ALPHA) ** i for i in range(n - 1, -1, -1)], dtype=np.float64)
    return raw / raw.sum()


def _merge_response_level(
    feature_vectors: list[FeatureVectorData],
    ewma_weights: np.ndarray,
) -> ResponseLevelFeatures:
    all_latency_means: list[float] = []
    all_latency_stds: list[float] = []
    all_latency_p50: list[float] = []
    all_latency_p95: list[float] = []
    all_latency_p99: list[float] = []
    all_response_size_means: list[float] = []
    all_response_size_stds: list[float] = []
    all_response_size_p95: list[float] = []
    status_code_accum: dict[str, float] = {}
    entropy_values: list[float] = []
    sample_weights: list[int] = []
    indices: list[int] = []

    for i, fv in enumerate(feature_vectors):
        w = fv.sample_count
        if w == 0:
            continue
        indices.append(i)
        sample_weights.append(w)
        rl = fv.response_level
        all_latency_means.append(rl.latency.mean)
        all_latency_stds.append(rl.latency.std)
        all_latency_p50.append(rl.latency.p50)
        all_latency_p95.append(rl.latency.p95)
        all_latency_p99.append(rl.latency.p99)
        all_response_size_means.append(rl.response_size.mean)
        all_response_size_stds.append(rl.response_size.std)
        all_response_size_p95.append(rl.response_size.p95)
        entropy_values.append(rl.payload_entropy)

        for code, rate in rl.status_codes.items():
            status_code_accum[code] = status_code_accum.get(code, 0.0) + rate * w

    if not indices:
        return ResponseLevelFeatures()

    ew = ewma_weights[np.array(indices)] if len(ewma_weights) > len(indices) else ewma_weights[:len(indices)]
    ew = ew / ew.sum() if ew.sum() > 0 else ew

    total_sample_weight = sum(sample_weights)

    combined_weights = np.array(sample_weights, dtype=np.float64) * ew
    combined_weights = combined_weights / combined_weights.sum() if combined_weights.sum() > 0 else combined_weights

    valid_weights = combined_weights if combined_weights.sum() > 0 else None

    latency = LatencyStats(
        p50=float(np.average(all_latency_p50, weights=valid_weights)),
        p95=float(np.average(all_latency_p95, weights=valid_weights)),
        p99=float(np.average(all_latency_p99, weights=valid_weights)),
        mean=float(np.average(all_latency_means, weights=valid_weights)),
        std=float(np.average(all_latency_stds, weights=valid_weights)),
    )

    response_size = ResponseSizeStats(
        mean=float(np.average(all_response_size_means, weights=valid_weights)),
        std=float(np.average(all_response_size_stds, weights=valid_weights)),
        p95=float(np.average(all_response_size_p95, weights=valid_weights)),
    )

    normalized_status = {
        code: round(total / total_sample_weight, 6)
        for code, total in status_code_accum.items()
    } if total_sample_weight > 0 else {}

    payload_entropy = float(np.average(entropy_values, weights=valid_weights)) if entropy_values else 0.0

    return ResponseLevelFeatures(
        latency=latency,
        status_codes=normalized_status,
        response_size=response_size,
        payload_entropy=round(payload_entropy, 4),
    )


def _merge_field_features(
    feature_vectors: list[FeatureVectorData],
    ewma_weights: np.ndarray,
) -> dict[str, FieldFeatures]:
    all_fields: set[str] = set()
    for fv in feature_vectors:
        all_fields.update(fv.fields.keys())

    merged: dict[str, FieldFeatures] = {}
    for field_path in all_fields:
        field_data: list[tuple[FieldFeatures, int, int]] = []
        for i, fv in enumerate(feature_vectors):
            if field_path in fv.fields:
                field_data.append((fv.fields[field_path], fv.sample_count, i))

        if not field_data:
            continue

        merged[field_path] = _merge_single_field(field_data, ewma_weights)

    return merged


def _merge_single_field(
    field_data: list[tuple[FieldFeatures, int, int]],
    ewma_weights: np.ndarray,
) -> FieldFeatures:
    total_weight = sum(w for _, w, _ in field_data)
    if total_weight == 0:
        return FieldFeatures()

    indices = np.array([idx for _, _, idx in field_data])
    sample_w = np.array([w for _, w, _ in field_data], dtype=np.float64)
    ew = ewma_weights[indices] if len(ewma_weights) > max(indices) else np.ones(len(indices), dtype=np.float64)

    combined = sample_w * ew
    combined = combined / combined.sum() if combined.sum() > 0 else combined
    valid_combined = combined if combined.sum() > 0 else None

    features_list = [f for f, _, _ in field_data]

    presence_rate = float(np.average([f.presence_rate for f in features_list], weights=valid_combined))
    null_rate = float(np.average([f.null_rate for f in features_list], weights=valid_combined))
    type_consistency = float(np.average([f.type_consistency for f in features_list], weights=valid_combined))
    dominant_type = features_list[-1].dominant_type

    merged = FieldFeatures(
        presence_rate=round(presence_rate, 6),
        null_rate=round(null_rate, 6),
        type_consistency=round(type_consistency, 6),
        dominant_type=dominant_type,
    )

    numeric_fields = [(f, w, i) for f, w, i in field_data if f.mean is not None]
    if numeric_fields:
        nw_indices = np.array([i for _, _, i in numeric_fields])
        nw_sample = np.array([w for _, w, _ in numeric_fields], dtype=np.float64)
        nw_ew = ewma_weights[nw_indices] if len(ewma_weights) > max(nw_indices) else np.ones(len(nw_indices), dtype=np.float64)
        nw_combined = nw_sample * nw_ew
        nw_combined = nw_combined / nw_combined.sum() if nw_combined.sum() > 0 else nw_combined
        valid_nw = nw_combined if nw_combined.sum() > 0 else None
        nf = [f for f, _, _ in numeric_fields]

        merged.mean = round(float(np.average([f.mean or 0.0 for f in nf], weights=valid_nw)), 6)
        merged.std = round(float(np.average([f.std or 0.0 for f in nf], weights=valid_nw)), 6)
        merged.p25 = round(float(np.average([f.p25 or 0.0 for f in nf], weights=valid_nw)), 6)
        merged.p50 = round(float(np.average([f.p50 or 0.0 for f in nf], weights=valid_nw)), 6)
        merged.p75 = round(float(np.average([f.p75 or 0.0 for f in nf], weights=valid_nw)), 6)
        merged.p95 = round(float(np.average([f.p95 or 0.0 for f in nf], weights=valid_nw)), 6)
        merged.p99 = round(float(np.average([f.p99 or 0.0 for f in nf], weights=valid_nw)), 6)

        min_vals = [f.min_val for f in nf if f.min_val is not None]
        max_vals = [f.max_val for f in nf if f.max_val is not None]
        if min_vals:
            merged.min_val = round(min(min_vals), 6)
        if max_vals:
            merged.max_val = round(max(max_vals), 6)

    string_fields = [(f, w, i) for f, w, i in field_data if f.mean_length is not None]
    if string_fields:
        sw_indices = np.array([i for _, _, i in string_fields])
        sw_sample = np.array([w for _, w, _ in string_fields], dtype=np.float64)
        sw_ew = ewma_weights[sw_indices] if len(ewma_weights) > max(sw_indices) else np.ones(len(sw_indices), dtype=np.float64)
        sw_combined = sw_sample * sw_ew
        sw_combined = sw_combined / sw_combined.sum() if sw_combined.sum() > 0 else sw_combined
        valid_sw = sw_combined if sw_combined.sum() > 0 else None
        sf = [f for f, _, _ in string_fields]

        merged.mean_length = round(float(np.average([f.mean_length or 0.0 for f in sf], weights=valid_sw)), 6)
        merged.std_length = round(float(np.average([f.std_length or 0.0 for f in sf], weights=valid_sw)), 6)

        vocab_sizes = [f.vocabulary_size for f in sf if f.vocabulary_size is not None]
        if vocab_sizes:
            merged.vocabulary_size = max(vocab_sizes)

        entropies = [f.vocabulary_entropy for f in sf if f.vocabulary_entropy is not None]
        if entropies:
            ent_weights = sw_combined[:len(entropies)]
            ent_weights = ent_weights / ent_weights.sum() if ent_weights.sum() > 0 else ent_weights
            valid_ent = ent_weights if ent_weights.sum() > 0 else None
            merged.vocabulary_entropy = round(float(np.average(entropies, weights=valid_ent)), 6)

        enum_dists = [f.enum_distribution for f in sf if f.enum_distribution]
        if enum_dists:
            combined_enum: dict[str, float] = {}
            enum_w_list = [w for f, w, _ in string_fields if f.enum_distribution]
            total_enum_w = sum(enum_w_list)
            if total_enum_w > 0:
                for dist, w in zip(enum_dists, enum_w_list):
                    for val, freq in dist.items():
                        combined_enum[val] = combined_enum.get(val, 0.0) + freq * w / total_enum_w
                merged.enum_distribution = {k: round(v, 6) for k, v in combined_enum.items()}
                merged.enum_values = sorted(combined_enum.keys())[:50]

    return merged
