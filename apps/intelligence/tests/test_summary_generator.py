"""
Aggressive tests for app.core.summary_generator — format correctness for all drift types.
"""
from __future__ import annotations

import pytest

from app.core.summary_generator import generate_alert_summary
from app.schemas.scoring import (
    AlertSeverity,
    DriftComponent,
    DriftResult,
    DriftType,
)

def _comp(dtype: DriftType, z: float = 3.0, w: float = 1.0, **kw) -> DriftComponent:
    defaults = {
        "feature_name": f"field.test.{dtype.value}",
        "drift_type": dtype,
        "baseline_value": 0.5,
        "observed_value": 0.9,
        "deviation_z": z,
        "deviation_pct": 80.0,
        "weight": w,
    }
    defaults.update(kw)
    return DriftComponent(**defaults)


class TestGenerateAlertSummary:
    def test_no_components(self):
        result = DriftResult(total_score=0.0, components=[])
        assert generate_alert_summary(result) == "No significant behavioral drift detected."

    def test_null_rate_spike_format(self):
        result = DriftResult(
            total_score=5.0,
            components=[_comp(DriftType.NULL_RATE_SPIKE, feature_name="field.email.null_rate")],
            severity=AlertSeverity.MEDIUM,
        )
        summary = generate_alert_summary(result)
        assert "[MEDIUM]" in summary
        assert "null rate increased" in summary

    def test_field_disappeared_format(self):
        result = DriftResult(
            total_score=6.0,
            components=[_comp(DriftType.FIELD_DISAPPEARED, feature_name="field.name",
                              baseline_value=0.95, observed_value=0.0)],
            severity=AlertSeverity.HIGH,
        )
        summary = generate_alert_summary(result)
        assert "field disappeared" in summary

    def test_latency_shift_format(self):
        result = DriftResult(
            total_score=4.0,
            components=[_comp(DriftType.LATENCY_SHIFT, feature_name="latency.p95",
                              baseline_value=100.0, observed_value=500.0, deviation_pct=400.0)],
            severity=AlertSeverity.MEDIUM,
        )
        summary = generate_alert_summary(result)
        assert "latency shifted" in summary
        assert "100.0" in summary
        assert "500.0" in summary

    def test_enum_collapse_format(self):
        result = DriftResult(
            total_score=3.0,
            components=[_comp(DriftType.ENUM_COLLAPSE, feature_name="field.method.enum_distribution")],
            severity=AlertSeverity.LOW,
        )
        summary = generate_alert_summary(result)
        assert "JSD-based" in summary

    def test_structural_change_format(self):
        result = DriftResult(
            total_score=4.0,
            components=[_comp(DriftType.STRUCTURAL_CHANGE, feature_name="field.debug_flag",
                              observed_value=0.90)],
            severity=AlertSeverity.MEDIUM,
        )
        summary = generate_alert_summary(result)
        assert "new field appeared" in summary

    def test_schema_type_change_format(self):
        result = DriftResult(
            total_score=5.0,
            components=[_comp(DriftType.SCHEMA_TYPE_CHANGE, feature_name="field.val.type")],
            severity=AlertSeverity.MEDIUM,
        )
        summary = generate_alert_summary(result)
        assert "field type changed" in summary

    def test_top_three_only(self):
        comps = [
            _comp(DriftType.LATENCY_SHIFT, z=2.0, w=0.8),
            _comp(DriftType.NULL_RATE_SPIKE, z=3.0, w=1.5),
            _comp(DriftType.FIELD_DISAPPEARED, z=5.0, w=2.0),
            _comp(DriftType.RESPONSE_SIZE_SHIFT, z=1.0, w=0.7),
            _comp(DriftType.PAYLOAD_ENTROPY_DROP, z=1.5, w=1.1),
        ]
        result = DriftResult(total_score=7.0, components=comps, severity=AlertSeverity.HIGH)
        summary = generate_alert_summary(result)
        # Highest weighted impact: FIELD_DISAPPEARED (5*2=10), NULL_RATE (3*1.5=4.5), LATENCY (2*0.8=1.6)
        assert "field disappeared" in summary
        assert "null rate increased" in summary

    def test_severity_in_header(self):
        result = DriftResult(
            total_score=9.5,
            components=[_comp(DriftType.LATENCY_SHIFT)],
            severity=AlertSeverity.CRITICAL,
        )
        summary = generate_alert_summary(result)
        assert "[CRITICAL]" in summary
        assert "9.50" in summary
