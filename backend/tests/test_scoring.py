"""Tests for the CESI scoring engine — classify_severity + compute_cesi_score."""

from __future__ import annotations

import pytest

from frr.db.models import SeverityBand, SignalLayer
from frr.scoring.engine import LAYER_WEIGHTS, classify_severity, compute_cesi_score


# ── classify_severity ──────────────────────────────────────────────────


class TestClassifySeverity:
    """Severity band classification from a 0–100 score."""

    @pytest.mark.parametrize(
        "score,expected",
        [
            (0.0, SeverityBand.STABLE),
            (10.0, SeverityBand.STABLE),
            (20.0, SeverityBand.STABLE),
            (20.1, SeverityBand.ELEVATED),
            (30.0, SeverityBand.ELEVATED),
            (40.0, SeverityBand.ELEVATED),
            (40.1, SeverityBand.CONCERNING),
            (50.0, SeverityBand.CONCERNING),
            (60.0, SeverityBand.CONCERNING),
            (60.1, SeverityBand.HIGH_RISK),
            (70.0, SeverityBand.HIGH_RISK),
            (80.0, SeverityBand.HIGH_RISK),
            (80.1, SeverityBand.CRITICAL),
            (90.0, SeverityBand.CRITICAL),
            (100.0, SeverityBand.CRITICAL),
        ],
    )
    def test_band_boundaries(self, score: float, expected: SeverityBand):
        assert classify_severity(score) == expected


# ── compute_cesi_score ─────────────────────────────────────────────────


class TestComputeCesiScore:
    """CESI score computation with amplification logic."""

    def test_all_zero_anomalies(self):
        anomalies = {layer: 0.0 for layer in SignalLayer}
        score, amp_applied, breakdown = compute_cesi_score(anomalies)
        assert score == pytest.approx(0.0)
        assert amp_applied is False
        assert len(breakdown) == len(SignalLayer)

    def test_uniform_50_no_amplification(self):
        """All layers at 50 → some layers may not spike → depends on threshold."""
        anomalies = {layer: 50.0 for layer in SignalLayer}
        score, amp_applied, breakdown = compute_cesi_score(
            anomalies,
            spike_threshold=0.6,
            min_layers=3,
        )
        # Weighted sum: 0.2*50 + 0.2*50 + 0.3*50 + 0.3*50 = 50
        assert score == pytest.approx(50.0, rel=0.1)

    def test_all_layers_at_100(self):
        """All layers maxed out → amplification should kick in."""
        anomalies = {layer: 100.0 for layer in SignalLayer}
        score, amp_applied, breakdown = compute_cesi_score(
            anomalies,
            gamma=15.0,
            spike_threshold=0.6,
            min_layers=3,
        )
        # All 4 layers spike: amplification = 1 + 15 * max(0, 4-2)/100 = 1.3
        # Weighted sum = 100, score = min(100*1.3, 100) = 100 (clamped)
        assert score == pytest.approx(100.0)
        assert amp_applied is True

    def test_score_clamped_at_100(self):
        """Score must not exceed 100 even with amplification."""
        anomalies = {layer: 95.0 for layer in SignalLayer}
        score, _, _ = compute_cesi_score(
            anomalies,
            gamma=15.0,
            spike_threshold=0.6,
            min_layers=3,
        )
        assert score <= 100.0

    def test_score_never_negative(self):
        """Score must be >= 0 even with weird inputs."""
        anomalies = {layer: 0.0 for layer in SignalLayer}
        score, _, _ = compute_cesi_score(anomalies)
        assert score >= 0.0

    def test_partial_layers(self):
        """Only some layers present — missing ones default to 0."""
        anomalies = {
            SignalLayer.ENERGY_CONFLICT: 80.0,
            SignalLayer.SUPPLY_CHAIN: 60.0,
        }
        score, amp_applied, breakdown = compute_cesi_score(
            anomalies,
            spike_threshold=0.6,
            min_layers=3,
        )
        # Only 2 layers spiking → no amplification
        expected = 0.3 * 60.0 + 0.3 * 80.0  # + 0 for research + 0 for patent
        assert score == pytest.approx(expected, rel=0.01)
        assert amp_applied is False

    def test_amplification_threshold(self):
        """Exactly n_spike == min_layers triggers amplification."""
        anomalies = {
            SignalLayer.RESEARCH_FUNDING: 70.0,
            SignalLayer.PATENT_ACTIVITY: 70.0,
            SignalLayer.SUPPLY_CHAIN: 70.0,
            SignalLayer.ENERGY_CONFLICT: 0.0,
        }
        _, amp_applied, _ = compute_cesi_score(
            anomalies,
            gamma=15.0,
            spike_threshold=0.6,
            min_layers=3,
        )
        assert amp_applied is True

    def test_layer_breakdown_keys(self):
        """Breakdown should contain all layer names."""
        anomalies = {layer: 50.0 for layer in SignalLayer}
        _, _, breakdown = compute_cesi_score(anomalies)
        for layer in SignalLayer:
            assert layer.value in breakdown
            assert "raw_anomaly" in breakdown[layer.value]
            assert "weight" in breakdown[layer.value]
            assert "contribution" in breakdown[layer.value]

    def test_weights_sum_to_one(self):
        """Layer weights must sum to 1.0."""
        total = sum(LAYER_WEIGHTS.values())
        assert total == pytest.approx(1.0, rel=1e-9)

    def test_empty_anomalies(self):
        """No anomalies dict → score should be 0."""
        score, amp_applied, _ = compute_cesi_score({})
        assert score == pytest.approx(0.0)
        assert amp_applied is False
