from __future__ import annotations

from app.schemas.scoring import DriftComponent, DriftResult, DriftType

_DRIFT_TYPE_LABELS: dict[DriftType, str] = {
    DriftType.NULL_RATE_SPIKE: "null rate increased",
    DriftType.FIELD_DISAPPEARED: "field disappeared",
    DriftType.ENUM_COLLAPSE: "enum distribution collapsed",
    DriftType.NUMERIC_DISTRIBUTION_SHIFT: "numeric distribution shifted",
    DriftType.PAYLOAD_ENTROPY_DROP: "payload entropy dropped",
    DriftType.LATENCY_SHIFT: "latency shifted",
    DriftType.RESPONSE_SIZE_SHIFT: "response size shifted",
    DriftType.TYPE_CONSISTENCY_DROP: "type consistency dropped",
    DriftType.VOCABULARY_COLLAPSE: "vocabulary collapsed",
    DriftType.STATUS_CODE_SHIFT: "error rate increased",
    DriftType.STRUCTURAL_CHANGE: "new field appeared",
    DriftType.SCHEMA_TYPE_CHANGE: "field type changed",
    DriftType.PRESENCE_RATE_DROP: "field presence rate dropped",
}


def generate_alert_summary(drift_result: DriftResult) -> str:
    if not drift_result.components:
        return "No significant behavioral drift detected."

    top_components = sorted(
        drift_result.components,
        key=lambda c: abs(c.deviation_z) * c.weight,
        reverse=True,
    )[:3]

    parts: list[str] = []
    for comp in top_components:
        parts.append(_describe_component(comp))

    severity_label = drift_result.severity.value.upper() if drift_result.severity else "NONE"
    header = f"[{severity_label}] Drift score: {drift_result.total_score:.2f}."

    return f"{header} {'; '.join(parts)}."


def _describe_component(comp: DriftComponent) -> str:
    label = _DRIFT_TYPE_LABELS.get(comp.drift_type, comp.drift_type.value)
    field_name = comp.feature_name.replace("field.", "").replace(".", " → ")

    if comp.drift_type == DriftType.NULL_RATE_SPIKE:
        return (
            f"{field_name}: {label} from "
            f"{comp.baseline_value:.1%} to {comp.observed_value:.1%} "
            f"(z={comp.deviation_z:.1f})"
        )

    if comp.drift_type == DriftType.FIELD_DISAPPEARED:
        return f"{field_name}: {label} (was present {comp.baseline_value:.0%} of the time)"

    if comp.drift_type in (DriftType.LATENCY_SHIFT, DriftType.RESPONSE_SIZE_SHIFT):
        return (
            f"{field_name}: {label} from "
            f"{comp.baseline_value:.1f} to {comp.observed_value:.1f} "
            f"({comp.deviation_pct:+.1f}%)"
        )

    if comp.drift_type == DriftType.ENUM_COLLAPSE:
        return f"{field_name}: {label} (JSD-based, z={comp.deviation_z:.1f})"

    if comp.drift_type == DriftType.STRUCTURAL_CHANGE:
        return f"{field_name}: {label} with {comp.observed_value:.0%} presence"

    if comp.drift_type == DriftType.SCHEMA_TYPE_CHANGE:
        return f"{field_name}: {label}"

    return (
        f"{field_name}: {label} "
        f"(baseline={comp.baseline_value:.4f}, observed={comp.observed_value:.4f}, "
        f"z={comp.deviation_z:.1f})"
    )
