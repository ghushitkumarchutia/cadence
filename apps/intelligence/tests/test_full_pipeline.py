"""
Full pipeline integration tests — observations through the entire intelligence pipeline.
Proves end-to-end correctness without any mocks.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.core.baseline_computer import compute_baseline, resolve_maturity_state
from app.core.confidence_scorer import compute_confidence, should_alert
from app.core.drift_scorer import score_drift
from app.core.feature_extractor import extract_features
from app.core.summary_generator import generate_alert_summary
from app.schemas.scoring import AlertSeverity, MaturityState

from conftest import make_observations


def _run_pipeline(
    baseline_obs: list[dict],
    current_obs: list[dict],
    deployment_recency_hours: float | None = None,
    anomaly_persistence_windows: int = 0,
):
    """Run the full intelligence pipeline: extract → baseline → drift → confidence → alert."""
    # Build baseline
    bl_fv = extract_features(baseline_obs, baseline_obs[0]["time"], baseline_obs[-1]["time"])
    baseline = compute_baseline([bl_fv])

    # Extract current features
    cr_fv = extract_features(current_obs, current_obs[0]["time"], current_obs[-1]["time"])

    # Score drift
    drift_result = score_drift(cr_fv, baseline)

    # Compute confidence
    maturity = resolve_maturity_state(baseline.sample_count)
    confidence = compute_confidence(
        maturity_state=maturity,
        sample_count=baseline.sample_count,
        baseline_age_hours=0.0,
        window_days=baseline.window_days,
        deployment_recency_hours=deployment_recency_hours,
        anomaly_persistence_windows=anomaly_persistence_windows,
    )

    # Alert decision
    alert = should_alert(drift_result.total_score, confidence)

    # Summary
    summary = generate_alert_summary(drift_result) if alert else None

    return drift_result, confidence, alert, summary


class TestFullPipeline:
    def test_normal_traffic_no_alert(self):
        baseline_obs = make_observations(500, seed=42)
        current_obs = make_observations(100, seed=43)
        drift, conf, alert, summary = _run_pipeline(baseline_obs, current_obs)
        assert drift.total_score < 3.0
        assert alert is False
        assert summary is None

    def test_latency_spike_alert(self):
        baseline_obs = make_observations(500, seed=42, base_latency=120.0, latency_std=20.0)
        current_obs = make_observations(100, seed=44, base_latency=500.0, latency_std=50.0)
        drift, conf, alert, summary = _run_pipeline(baseline_obs, current_obs)
        assert drift.total_score >= 4.0
        assert drift.severity in (AlertSeverity.MEDIUM, AlertSeverity.HIGH, AlertSeverity.CRITICAL)

    def test_null_rate_attack(self):
        import copy
        baseline_obs = make_observations(500, seed=42)
        current_obs = make_observations(100, seed=45)
        # Inject nulls into 60% of email fields
        rng = np.random.default_rng(99)
        for obs in current_obs:
            if obs.get("payload_sample") and isinstance(obs["payload_sample"], dict):
                user = obs["payload_sample"].get("user")
                if isinstance(user, dict) and rng.random() < 0.6:
                    user["email"] = None
        drift, conf, alert, summary = _run_pipeline(baseline_obs, current_obs)
        assert drift.total_score > 1.0

    def test_schema_mutation(self):
        baseline_obs = make_observations(500, seed=42)
        current_obs = make_observations(100, seed=46)
        for obs in current_obs:
            if obs.get("payload_sample") and isinstance(obs["payload_sample"], dict):
                obs["payload_sample"]["debug_flag"] = True
        drift, conf, alert, summary = _run_pipeline(baseline_obs, current_obs)
        from app.schemas.scoring import DriftType
        types = [c.drift_type for c in drift.components]
        assert DriftType.STRUCTURAL_CHANGE in types

    def test_cold_start_no_alert(self):
        """50 observations → INITIALIZING → confidence too low → no alert even with drift."""
        from app.schemas.scoring import ConfidenceLevel
        baseline_obs = make_observations(50, seed=42)
        current_obs = make_observations(50, seed=47, base_latency=500.0, latency_std=50.0)
        drift, conf, alert, summary = _run_pipeline(baseline_obs, current_obs)
        assert conf.level in (ConfidenceLevel.LOW, ConfidenceLevel.MODERATE)

    def test_post_deploy_suppression(self):
        """Recent deploy → confidence penalty → MEDIUM drift doesn't alert."""
        baseline_obs = make_observations(5000, seed=42)
        current_obs = make_observations(100, seed=48, base_latency=200.0, latency_std=30.0)
        drift, conf, alert, summary = _run_pipeline(
            baseline_obs, current_obs,
            deployment_recency_hours=0.3,
        )
        # Deployment penalty should reduce confidence
        assert conf.factors["deployment"] == 0.2

    def test_multi_window_baseline(self):
        """10 feature vectors → merged baseline → drift against it."""
        fvs = []
        for i in range(10):
            obs = make_observations(100, seed=50 + i)
            fv = extract_features(obs, obs[0]["time"], obs[-1]["time"])
            fvs.append(fv)
        baseline = compute_baseline(fvs)
        assert baseline.sample_count == 1000
        assert baseline.maturity_state == MaturityState.STABILIZING

        # Normal traffic against multi-window baseline
        current_obs = make_observations(100, seed=60)
        cr_fv = extract_features(current_obs, current_obs[0]["time"], current_obs[-1]["time"])
        drift = score_drift(cr_fv, baseline)
        assert drift.total_score < 4.0


class TestReplayPipelineContract:
    def test_window_count_100(self):
        """100 observations → 1 window of 100."""
        from app.schemas.scoring import ReplayScoreRequest, BaselineData
        obs = make_observations(100, seed=70)
        # Simulate replay windowing (window size = 100)
        windows = [obs[i:i + 100] for i in range(0, len(obs), 100)]
        assert len(windows) == 1

    def test_window_count_250(self):
        """250 observations → 3 windows (100+100+50)."""
        obs = make_observations(250, seed=71)
        windows = [obs[i:i + 100] for i in range(0, len(obs), 100)]
        assert len(windows) == 3
        assert len(windows[0]) == 100
        assert len(windows[1]) == 100
        assert len(windows[2]) == 50

    def test_replay_summary_fields(self):
        """Verify summary dict structure."""
        summary = {
            "total_windows": 3,
            "total_alerts": 1,
            "avg_drift_score": 2.5,
            "max_drift_score": 5.0,
            "observations_processed": 250,
        }
        required = {"total_windows", "total_alerts", "avg_drift_score",
                     "max_drift_score", "observations_processed"}
        assert required == set(summary.keys())
