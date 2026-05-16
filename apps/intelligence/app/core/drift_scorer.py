from __future__ import annotations

from app.core.divergence import (
    jensen_shannon_divergence,
    population_stability_index,
    proportion_z_test,
    rate_z_score,
    safe_pct_change,
)
from app.schemas.features import (
    DominantType,
    FeatureVectorData,
    FieldFeatures,
)
from app.schemas.scoring import (
    DRIFT_TYPE_WEIGHTS,
    AlertSeverity,
    BaselineData,
    DriftComponent,
    DriftResult,
    DriftType,
)

_ALERT_THRESHOLDS: list[tuple[float, float, AlertSeverity | None]] = [
    (0.0, 2.0, None),
    (2.0, 4.0, AlertSeverity.LOW),
    (4.0, 6.0, AlertSeverity.MEDIUM),
    (6.0, 8.0, AlertSeverity.HIGH),
    (8.0, 10.0, AlertSeverity.CRITICAL),
]

_NULL_RATE_ABS_THRESHOLD = 0.05
_PRESENCE_RATE_ABS_THRESHOLD = 0.1
_TYPE_CONSISTENCY_BASELINE_MIN = 0.95
_TYPE_CONSISTENCY_DROP_MIN = 0.05
_Z_SCORE_TRIGGER = 2.0
_Z_SCORE_CAP = 10.0
_ENTROPY_DROP_RATIO_TRIGGER = 0.3
_VOCAB_SIZE_COLLAPSE_RATIO = 0.5
_STATUS_CODE_DIFF_MIN = 0.01
_FIELD_PRESENCE_SIGNIFICANCE = 0.5
_JSD_TRIGGER = 0.15
_PSI_TRIGGER = 0.25


def score_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
    model_version: str = "1.0.0",
) -> DriftResult:
    if baseline.sample_count == 0:
        return DriftResult(
            total_score=0.0,
            components=[],
            model_version=model_version,
        )

    components: list[DriftComponent] = []

    components.extend(_score_latency_drift(current, baseline))
    components.extend(_score_status_code_drift(current, baseline))
    components.extend(_score_response_size_drift(current, baseline))
    components.extend(_score_payload_entropy_drift(current, baseline))
    components.extend(_score_schema_drift(current, baseline))
    components.extend(_score_field_drift(current, baseline))

    total_score = _compute_weighted_score(components)
    severity = _map_severity(total_score)
    alert_type = _determine_alert_type(components) if severity else None

    return DriftResult(
        total_score=round(total_score, 4),
        components=components,
        model_version=model_version,
        alert_type=alert_type,
        severity=severity,
    )


def _clamp_z(z: float) -> float:
    sign = 1.0 if z >= 0 else -1.0
    return sign * min(abs(z), _Z_SCORE_CAP)


def _compute_weighted_score(components: list[DriftComponent]) -> float:
    if not components:
        return 0.0

    weighted_sum = sum(abs(c.deviation_z) * c.weight for c in components)
    total_weight = sum(c.weight for c in components)

    if total_weight == 0:
        return 0.0

    raw_score = weighted_sum / total_weight
    return min(10.0, raw_score)


def _map_severity(score: float) -> AlertSeverity | None:
    for low, high, severity in _ALERT_THRESHOLDS:
        if low <= score < high:
            return severity
    return AlertSeverity.CRITICAL


def _determine_alert_type(components: list[DriftComponent]) -> str:
    if not components:
        return "behavioral_drift"

    max_component = max(components, key=lambda c: abs(c.deviation_z) * c.weight)
    return max_component.drift_type.value


def _score_latency_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []
    bl = baseline.response_level.latency
    cr = current.response_level.latency

    if bl.std > 0 or bl.mean > 0:
        z_p95 = rate_z_score(cr.p95, bl.p95, bl.std)
        if abs(z_p95) >= _Z_SCORE_TRIGGER:
            components.append(DriftComponent(
                feature_name="latency.p95",
                drift_type=DriftType.LATENCY_SHIFT,
                baseline_value=bl.p95,
                observed_value=cr.p95,
                deviation_z=round(_clamp_z(z_p95), 4),
                deviation_pct=round(safe_pct_change(cr.p95, bl.p95), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.LATENCY_SHIFT],
            ))

        z_mean = rate_z_score(cr.mean, bl.mean, bl.std)
        if abs(z_mean) >= _Z_SCORE_TRIGGER:
            components.append(DriftComponent(
                feature_name="latency.mean",
                drift_type=DriftType.LATENCY_SHIFT,
                baseline_value=bl.mean,
                observed_value=cr.mean,
                deviation_z=round(_clamp_z(z_mean), 4),
                deviation_pct=round(safe_pct_change(cr.mean, bl.mean), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.LATENCY_SHIFT],
            ))

    return components


def _score_status_code_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []
    bl_codes = baseline.response_level.status_codes
    cr_codes = current.response_level.status_codes

    if bl_codes and cr_codes:
        psi = population_stability_index(bl_codes, cr_codes)
        if psi >= _PSI_TRIGGER:
            all_codes = set(bl_codes.keys()) | set(cr_codes.keys())
            for code in all_codes:
                bl_rate = bl_codes.get(code, 0.0)
                cr_rate = cr_codes.get(code, 0.0)
                code_int = int(code) if code.isdigit() else 0

                if code_int < 400:
                    continue

                diff = cr_rate - bl_rate
                if abs(diff) > _STATUS_CODE_DIFF_MIN:
                    z = proportion_z_test(cr_rate, bl_rate, current.sample_count)
                    if abs(z) >= _Z_SCORE_TRIGGER:
                        components.append(DriftComponent(
                            feature_name=f"status_code.{code}_rate",
                            drift_type=DriftType.STATUS_CODE_SHIFT,
                            baseline_value=bl_rate,
                            observed_value=cr_rate,
                            deviation_z=round(_clamp_z(z), 4),
                            deviation_pct=round(safe_pct_change(cr_rate, bl_rate), 4),
                            weight=DRIFT_TYPE_WEIGHTS[DriftType.STATUS_CODE_SHIFT],
                        ))

    return components


def _score_response_size_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []
    bl = baseline.response_level.response_size
    cr = current.response_level.response_size

    if bl.std > 0 or bl.mean > 0:
        z = rate_z_score(cr.mean, bl.mean, bl.std)
        if abs(z) >= _Z_SCORE_TRIGGER:
            components.append(DriftComponent(
                feature_name="response_size.mean",
                drift_type=DriftType.RESPONSE_SIZE_SHIFT,
                baseline_value=bl.mean,
                observed_value=cr.mean,
                deviation_z=round(_clamp_z(z), 4),
                deviation_pct=round(safe_pct_change(cr.mean, bl.mean), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.RESPONSE_SIZE_SHIFT],
            ))

    return components


def _score_payload_entropy_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []
    bl_entropy = baseline.response_level.payload_entropy
    cr_entropy = current.response_level.payload_entropy

    if bl_entropy > 0.1:
        drop = bl_entropy - cr_entropy
        drop_ratio = drop / bl_entropy
        if drop > 0 and drop_ratio > _ENTROPY_DROP_RATIO_TRIGGER:
            z = drop_ratio * 5.0
            components.append(DriftComponent(
                feature_name="payload.entropy",
                drift_type=DriftType.PAYLOAD_ENTROPY_DROP,
                baseline_value=bl_entropy,
                observed_value=cr_entropy,
                deviation_z=round(min(z, _Z_SCORE_CAP), 4),
                deviation_pct=round(safe_pct_change(cr_entropy, bl_entropy), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.PAYLOAD_ENTROPY_DROP],
            ))

    return components


def _score_schema_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []
    bl_hash = baseline.response_level.schema_hash
    cr_hash = current.response_level.schema_hash

    if bl_hash and cr_hash and bl_hash != cr_hash:
        components.append(DriftComponent(
            feature_name="payload.schema_hash",
            drift_type=DriftType.STRUCTURAL_CHANGE,
            baseline_value=0.0,
            observed_value=1.0,
            deviation_z=4.0,
            deviation_pct=100.0,
            weight=DRIFT_TYPE_WEIGHTS[DriftType.STRUCTURAL_CHANGE],
        ))

    return components


def _score_field_drift(
    current: FeatureVectorData,
    baseline: BaselineData,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []

    for path, bl_field in baseline.fields.items():
        if path not in current.fields:
            if bl_field.presence_rate > _FIELD_PRESENCE_SIGNIFICANCE:
                components.append(DriftComponent(
                    feature_name=f"field.{path}",
                    drift_type=DriftType.FIELD_DISAPPEARED,
                    baseline_value=bl_field.presence_rate,
                    observed_value=0.0,
                    deviation_z=5.0,
                    deviation_pct=-100.0,
                    weight=DRIFT_TYPE_WEIGHTS[DriftType.FIELD_DISAPPEARED],
                ))
            continue

        cr_field = current.fields[path]

        null_drift = _score_null_rate_drift(path, cr_field, bl_field, current.sample_count)
        if null_drift:
            components.append(null_drift)

        type_drift = _score_type_consistency_drift(path, cr_field, bl_field)
        if type_drift:
            components.append(type_drift)

        type_change = _score_type_change(path, cr_field, bl_field)
        if type_change:
            components.append(type_change)

        presence_drift = _score_presence_rate_drift(path, cr_field, bl_field, current.sample_count)
        if presence_drift:
            components.append(presence_drift)

        numeric_drifts = _score_numeric_field_drift(path, cr_field, bl_field)
        components.extend(numeric_drifts)

        vocab_drift = _score_vocabulary_drift(path, cr_field, bl_field)
        if vocab_drift:
            components.append(vocab_drift)

        enum_drift = _score_enum_distribution_drift(path, cr_field, bl_field)
        if enum_drift:
            components.append(enum_drift)

    for path in current.fields:
        if path not in baseline.fields:
            cr_field = current.fields[path]
            if cr_field.presence_rate > _FIELD_PRESENCE_SIGNIFICANCE:
                components.append(DriftComponent(
                    feature_name=f"field.{path}",
                    drift_type=DriftType.STRUCTURAL_CHANGE,
                    baseline_value=0.0,
                    observed_value=cr_field.presence_rate,
                    deviation_z=3.0,
                    deviation_pct=100.0,
                    weight=DRIFT_TYPE_WEIGHTS[DriftType.STRUCTURAL_CHANGE],
                ))

    return components


def _score_null_rate_drift(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
    sample_count: int,
) -> DriftComponent | None:
    bl_null = baseline.null_rate
    cr_null = current.null_rate

    if cr_null - bl_null > _NULL_RATE_ABS_THRESHOLD:
        z = proportion_z_test(cr_null, bl_null, sample_count)
        if abs(z) >= _Z_SCORE_TRIGGER:
            return DriftComponent(
                feature_name=f"field.{path}.null_rate",
                drift_type=DriftType.NULL_RATE_SPIKE,
                baseline_value=bl_null,
                observed_value=cr_null,
                deviation_z=round(_clamp_z(z), 4),
                deviation_pct=round(safe_pct_change(cr_null, bl_null), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.NULL_RATE_SPIKE],
            )

    return None


def _score_type_consistency_drift(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
) -> DriftComponent | None:
    bl_tc = baseline.type_consistency
    cr_tc = current.type_consistency

    if bl_tc > _TYPE_CONSISTENCY_BASELINE_MIN and cr_tc < bl_tc - _TYPE_CONSISTENCY_DROP_MIN:
        std_approx = max(1.0 - bl_tc, 0.01)
        z = (bl_tc - cr_tc) / std_approx
        return DriftComponent(
            feature_name=f"field.{path}.type_consistency",
            drift_type=DriftType.TYPE_CONSISTENCY_DROP,
            baseline_value=bl_tc,
            observed_value=cr_tc,
            deviation_z=round(min(z, _Z_SCORE_CAP), 4),
            deviation_pct=round(safe_pct_change(cr_tc, bl_tc), 4),
            weight=DRIFT_TYPE_WEIGHTS[DriftType.TYPE_CONSISTENCY_DROP],
        )

    return None


def _score_type_change(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
) -> DriftComponent | None:
    if (
        baseline.dominant_type != DominantType.NULL
        and current.dominant_type != DominantType.NULL
        and baseline.dominant_type != current.dominant_type
        and baseline.type_consistency > 0.8
    ):
        return DriftComponent(
            feature_name=f"field.{path}.type",
            drift_type=DriftType.SCHEMA_TYPE_CHANGE,
            baseline_value=0.0,
            observed_value=1.0,
            deviation_z=5.0,
            deviation_pct=100.0,
            weight=DRIFT_TYPE_WEIGHTS[DriftType.SCHEMA_TYPE_CHANGE],
        )
    return None


def _score_presence_rate_drift(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
    sample_count: int,
) -> DriftComponent | None:
    bl_pr = baseline.presence_rate
    cr_pr = current.presence_rate

    if bl_pr - cr_pr > _PRESENCE_RATE_ABS_THRESHOLD and bl_pr > _FIELD_PRESENCE_SIGNIFICANCE:
        z = proportion_z_test(cr_pr, bl_pr, sample_count)
        if abs(z) >= _Z_SCORE_TRIGGER:
            return DriftComponent(
                feature_name=f"field.{path}.presence_rate",
                drift_type=DriftType.PRESENCE_RATE_DROP,
                baseline_value=bl_pr,
                observed_value=cr_pr,
                deviation_z=round(_clamp_z(z), 4),
                deviation_pct=round(safe_pct_change(cr_pr, bl_pr), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.PRESENCE_RATE_DROP],
            )
    return None


def _score_numeric_field_drift(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
) -> list[DriftComponent]:
    components: list[DriftComponent] = []

    if baseline.mean is not None and current.mean is not None:
        bl_std = baseline.std if baseline.std and baseline.std > 0 else 1.0
        z = rate_z_score(current.mean, baseline.mean, bl_std)
        if abs(z) >= _Z_SCORE_TRIGGER:
            components.append(DriftComponent(
                feature_name=f"field.{path}.mean",
                drift_type=DriftType.NUMERIC_DISTRIBUTION_SHIFT,
                baseline_value=baseline.mean,
                observed_value=current.mean,
                deviation_z=round(_clamp_z(z), 4),
                deviation_pct=round(safe_pct_change(current.mean, baseline.mean), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.NUMERIC_DISTRIBUTION_SHIFT],
            ))

    return components


def _score_vocabulary_drift(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
) -> DriftComponent | None:
    if (
        baseline.vocabulary_size is not None
        and current.vocabulary_size is not None
        and baseline.vocabulary_size > 0
    ):
        size_ratio = current.vocabulary_size / baseline.vocabulary_size
        if size_ratio < _VOCAB_SIZE_COLLAPSE_RATIO:
            z = (1.0 - size_ratio) * 6.0
            return DriftComponent(
                feature_name=f"field.{path}.vocabulary",
                drift_type=DriftType.VOCABULARY_COLLAPSE,
                baseline_value=float(baseline.vocabulary_size),
                observed_value=float(current.vocabulary_size),
                deviation_z=round(min(z, _Z_SCORE_CAP), 4),
                deviation_pct=round(safe_pct_change(float(current.vocabulary_size), float(baseline.vocabulary_size)), 4),
                weight=DRIFT_TYPE_WEIGHTS[DriftType.VOCABULARY_COLLAPSE],
            )

    return None


def _score_enum_distribution_drift(
    path: str,
    current: FieldFeatures,
    baseline: FieldFeatures,
) -> DriftComponent | None:
    if not baseline.enum_distribution or not current.enum_distribution:
        return None

    jsd = jensen_shannon_divergence(baseline.enum_distribution, current.enum_distribution)

    if jsd >= _JSD_TRIGGER:
        z = jsd * 8.0
        return DriftComponent(
            feature_name=f"field.{path}.enum_distribution",
            drift_type=DriftType.ENUM_COLLAPSE,
            baseline_value=baseline.vocabulary_entropy or 0.0,
            observed_value=current.vocabulary_entropy or 0.0,
            deviation_z=round(min(z, _Z_SCORE_CAP), 4),
            deviation_pct=round(safe_pct_change(
                current.vocabulary_entropy or 0.0,
                baseline.vocabulary_entropy or 0.0,
            ), 4),
            weight=DRIFT_TYPE_WEIGHTS[DriftType.ENUM_COLLAPSE],
        )

    return None
