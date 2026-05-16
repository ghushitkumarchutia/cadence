from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
import polars as pl

from app.core.divergence import shannon_entropy
from app.core.normalizer import compute_schema_hash
from app.schemas.features import (
    DominantType,
    FeatureVectorData,
    FieldFeatures,
    LatencyStats,
    ResponseLevelFeatures,
    ResponseSizeStats,
)

_CATEGORICAL_THRESHOLD = 50
_VOCABULARY_CAP = 1000
_MAX_FIELD_DEPTH = 5
_MAX_FIELD_COUNT = 500


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    f = float(v)
    if not math.isfinite(f):
        return default
    return f


def extract_features(
    observations: list[dict[str, Any]],
    window_start: str | datetime,
    window_end: str | datetime,
) -> FeatureVectorData:
    if not observations:
        ws = _ensure_datetime(window_start)
        we = _ensure_datetime(window_end)
        return FeatureVectorData(
            window_start=ws,
            window_end=we,
            sample_count=0,
        )

    ws = _ensure_datetime(window_start)
    we = _ensure_datetime(window_end)
    sample_count = len(observations)
    response_level = _extract_response_level(observations)
    fields = _extract_field_features(observations)

    return FeatureVectorData(
        window_start=ws,
        window_end=we,
        sample_count=sample_count,
        response_level=response_level,
        fields=fields,
    )


def _ensure_datetime(v: str | datetime) -> datetime:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _extract_response_level(observations: list[dict[str, Any]]) -> ResponseLevelFeatures:
    df = pl.DataFrame({
        "latency_ms": [obs.get("latency_ms", 0) for obs in observations],
        "status_code": [obs.get("status_code", 200) for obs in observations],
        "response_size_bytes": [obs.get("response_size_bytes") for obs in observations],
    })

    latency_stats = _compute_latency_stats_polars(df)
    status_code_dist = _compute_status_code_distribution_polars(df)
    response_size_stats = _compute_response_size_stats_polars(df)
    payload_entropy = _compute_payload_entropy(observations)
    schema_hash = _compute_schema_hash_from_observations(observations)
    schema_version = f"v:{schema_hash[:8]}" if schema_hash else None

    return ResponseLevelFeatures(
        latency=latency_stats,
        status_codes=status_code_dist,
        response_size=response_size_stats,
        payload_entropy=payload_entropy,
        schema_hash=schema_hash,
        schema_version=schema_version,
    )


def _compute_latency_stats_polars(df: pl.DataFrame) -> LatencyStats:
    col = df.get_column("latency_ms").drop_nulls().cast(pl.Float64)
    if col.is_empty():
        return LatencyStats()

    return LatencyStats(
        p50=_safe_float(col.quantile(0.50, interpolation="linear")),
        p95=_safe_float(col.quantile(0.95, interpolation="linear")),
        p99=_safe_float(col.quantile(0.99, interpolation="linear")),
        mean=_safe_float(col.mean()),
        std=_safe_float(col.std(ddof=1)) if len(col) > 1 else 0.0,
    )


def _compute_status_code_distribution_polars(df: pl.DataFrame) -> dict[str, float]:
    col = df.get_column("status_code").drop_nulls()
    if col.is_empty():
        return {}

    total = float(len(col))
    counts = col.value_counts()
    result: dict[str, float] = {}
    for row in counts.iter_rows():
        code_val, count_val = row[0], row[1]
        result[str(code_val)] = round(count_val / total, 6)
    return dict(sorted(result.items(), key=lambda x: -x[1]))


def _compute_response_size_stats_polars(df: pl.DataFrame) -> ResponseSizeStats:
    col = df.get_column("response_size_bytes").drop_nulls().cast(pl.Float64)
    if col.is_empty():
        return ResponseSizeStats()

    return ResponseSizeStats(
        mean=_safe_float(col.mean()),
        std=_safe_float(col.std(ddof=1)) if len(col) > 1 else 0.0,
        p95=_safe_float(col.quantile(0.95, interpolation="linear")),
    )


def _compute_payload_entropy(observations: list[dict[str, Any]]) -> float:
    hashes = [obs.get("payload_hash") for obs in observations if obs.get("payload_hash")]
    if not hashes:
        return 0.0

    counter = Counter(hashes)
    total = len(hashes)
    entropy = 0.0
    for count in counter.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def _compute_schema_hash_from_observations(observations: list[dict[str, Any]]) -> str | None:
    for obs in observations:
        payload = obs.get("payload_sample")
        if isinstance(payload, dict):
            return compute_schema_hash(payload)
    return None


def _extract_field_features(observations: list[dict[str, Any]]) -> dict[str, FieldFeatures]:
    payloads = [
        obs.get("payload_sample")
        for obs in observations
        if obs.get("payload_sample") is not None
    ]

    if not payloads:
        return {}

    all_paths: dict[str, list[Any]] = defaultdict(list)
    presence_counts: Counter[str] = Counter()
    total_payloads = len(payloads)

    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        visited: set[str] = set()
        _flatten_payload(payload, "", visited, all_paths, 0)
        for path in visited:
            presence_counts[path] += 1

    if len(all_paths) > _MAX_FIELD_COUNT:
        top_paths = sorted(all_paths.keys(), key=lambda p: presence_counts[p], reverse=True)[:_MAX_FIELD_COUNT]
        all_paths = {p: all_paths[p] for p in top_paths}

    fields: dict[str, FieldFeatures] = {}
    for path, values in all_paths.items():
        presence_rate = presence_counts[path] / total_payloads if total_payloads > 0 else 0.0
        fields[path] = _compute_field_features(values, presence_rate)

    return fields


def _flatten_payload(
    obj: Any,
    prefix: str,
    visited: set[str],
    all_paths: dict[str, list[Any]],
    depth: int,
) -> None:
    if depth > _MAX_FIELD_DEPTH:
        return

    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            visited.add(path)
            if isinstance(value, (dict, list)):
                _flatten_payload(value, path, visited, all_paths, depth + 1)
            else:
                all_paths[path].append(value)
    elif isinstance(obj, list):
        arr_path = f"{prefix}[]" if prefix else "[]"
        if arr_path not in visited:
            visited.add(arr_path)
        for item in obj:
            if isinstance(item, dict):
                _flatten_payload(item, arr_path, visited, all_paths, depth + 1)
            else:
                all_paths[arr_path].append(item)


def _compute_field_features(
    values: list[Any],
    presence_rate: float,
) -> FieldFeatures:
    null_count = sum(1 for v in values if v is None)
    total = len(values)
    null_rate = null_count / total if total > 0 else 0.0

    non_null_values = [v for v in values if v is not None]
    type_counts = Counter(type(v).__name__ for v in non_null_values)
    dominant_type_str = type_counts.most_common(1)[0][0] if type_counts else "null"
    dominant_type = _map_python_type(dominant_type_str)
    type_consistency = (
        type_counts.most_common(1)[0][1] / len(non_null_values)
        if non_null_values
        else 0.0
    )

    features = FieldFeatures(
        presence_rate=round(presence_rate, 6),
        null_rate=round(null_rate, 6),
        type_consistency=round(type_consistency, 6),
        dominant_type=dominant_type,
    )

    if dominant_type == DominantType.NUMBER:
        numeric_values = [float(v) for v in non_null_values if isinstance(v, (int, float)) and _is_finite(float(v))]
        if numeric_values:
            arr = np.array(numeric_values, dtype=np.float64)
            features.mean = round(_safe_float(np.mean(arr)), 6)
            features.std = round(_safe_float(np.std(arr, ddof=1)), 6) if len(arr) > 1 else 0.0
            features.p25 = round(_safe_float(np.percentile(arr, 25)), 6)
            features.p50 = round(_safe_float(np.percentile(arr, 50)), 6)
            features.p75 = round(_safe_float(np.percentile(arr, 75)), 6)
            features.p95 = round(_safe_float(np.percentile(arr, 95)), 6)
            features.p99 = round(_safe_float(np.percentile(arr, 99)), 6)
            features.min_val = round(_safe_float(np.min(arr)), 6)
            features.max_val = round(_safe_float(np.max(arr)), 6)

    elif dominant_type == DominantType.STRING:
        string_values = [v for v in non_null_values if isinstance(v, str)]
        if string_values:
            lengths = np.array([len(s) for s in string_values], dtype=np.float64)
            features.mean_length = round(_safe_float(np.mean(lengths)), 6)
            features.std_length = round(_safe_float(np.std(lengths, ddof=1)), 6) if len(lengths) > 1 else 0.0

            unique_values = set(string_values)
            vocab_size = min(len(unique_values), _VOCABULARY_CAP)
            features.vocabulary_size = vocab_size
            features.vocabulary_entropy = round(shannon_entropy(string_values), 6)

            if vocab_size <= _CATEGORICAL_THRESHOLD:
                counter = Counter(string_values)
                total_strings = len(string_values)
                features.enum_values = sorted(unique_values)[:_CATEGORICAL_THRESHOLD]
                features.enum_distribution = {
                    k: round(v / total_strings, 6) for k, v in counter.most_common(_CATEGORICAL_THRESHOLD)
                }

    elif dominant_type == DominantType.BOOLEAN:
        bool_values = [v for v in non_null_values if isinstance(v, bool)]
        if bool_values:
            true_count = sum(1 for v in bool_values if v)
            features.mean = round(true_count / len(bool_values), 6)

    elif dominant_type == DominantType.ARRAY:
        array_values = [v for v in non_null_values if isinstance(v, list)]
        if array_values:
            lengths = np.array([len(a) for a in array_values], dtype=np.float64)
            features.mean_length = round(_safe_float(np.mean(lengths)), 6)
            features.std_length = round(_safe_float(np.std(lengths, ddof=1)), 6) if len(lengths) > 1 else 0.0

    return features


def _is_finite(v: float) -> bool:
    return not (math.isnan(v) or math.isinf(v))


def _map_python_type(type_name: str) -> DominantType:
    mapping = {
        "str": DominantType.STRING,
        "int": DominantType.NUMBER,
        "float": DominantType.NUMBER,
        "bool": DominantType.BOOLEAN,
        "dict": DominantType.OBJECT,
        "list": DominantType.ARRAY,
        "NoneType": DominantType.NULL,
    }
    return mapping.get(type_name, DominantType.STRING)
