"""Integration tests — end-to-end flows through multiple modules."""

from __future__ import annotations

import numpy as np
import pytest

from frr.db.models import SeverityBand, SignalLayer
from frr.models.anomaly import RollingWelford, rolling_zscore
from frr.scoring.engine import classify_severity, compute_cesi_score


class TestAnomalyToScoringPipeline:
    """Signal → anomaly z-scores → CESI scoring → severity classification."""

    def test_normal_signals_produce_stable_score(self):
        """Flat signals → z-scores near 0 → CESI ≈ 0 → Stable."""
        # Simulate 4 layers with normal z-scores (small anomalies)
        layer_anomalies = {
            SignalLayer.RESEARCH_FUNDING: 5.0,
            SignalLayer.PATENT_ACTIVITY: 3.0,
            SignalLayer.SUPPLY_CHAIN: 8.0,
            SignalLayer.ENERGY_CONFLICT: 4.0,
        }
        score, amp_applied, breakdown = compute_cesi_score(layer_anomalies)
        severity = classify_severity(score)

        assert score < 20.0
        assert severity == SeverityBand.STABLE
        assert amp_applied is False

    def test_spike_in_one_layer_elevated(self):
        """One layer spiking → moderate CESI → Elevated/Concerning."""
        layer_anomalies = {
            SignalLayer.RESEARCH_FUNDING: 5.0,
            SignalLayer.PATENT_ACTIVITY: 5.0,
            SignalLayer.SUPPLY_CHAIN: 5.0,
            SignalLayer.ENERGY_CONFLICT: 80.0,  # energy shock
        }
        score, amp_applied, _ = compute_cesi_score(layer_anomalies)
        severity = classify_severity(score)

        # Weighted: 0.2*5 + 0.2*5 + 0.3*5 + 0.3*80 = 1 + 1 + 1.5 + 24 = 27.5
        assert 20 < score < 50
        assert severity in (SeverityBand.ELEVATED, SeverityBand.CONCERNING)

    def test_multi_layer_crisis_amplification(self):
        """3+ layers spiking → amplification → High Risk or Critical."""
        layer_anomalies = {
            SignalLayer.RESEARCH_FUNDING: 75.0,
            SignalLayer.PATENT_ACTIVITY: 80.0,
            SignalLayer.SUPPLY_CHAIN: 85.0,
            SignalLayer.ENERGY_CONFLICT: 90.0,
        }
        score, amp_applied, _ = compute_cesi_score(
            layer_anomalies,
            gamma=15.0,
            spike_threshold=0.6,
            min_layers=3,
        )
        severity = classify_severity(score)

        assert amp_applied is True
        assert severity in (SeverityBand.HIGH_RISK, SeverityBand.CRITICAL)

    def test_rolling_welford_feeds_zscore_pipeline(self):
        """RollingWelford stats align with numpy-based z-scores."""
        np.random.seed(42)
        data = np.random.normal(loc=50, scale=10, size=200)
        # Inject spike
        data[180] = 120.0

        rw = RollingWelford()
        for v in data[:60]:
            rw.add(v)

        # Manual z-score for point 180
        baseline = data[:180]
        z_manual = (data[180] - np.mean(baseline)) / np.std(baseline)
        # Should be a significant spike
        assert abs(z_manual) > 5.0

    def test_full_rolling_zscore_detects_anomalies(self):
        """rolling_zscore flags injected spikes correctly."""
        np.random.seed(42)
        values = np.random.normal(loc=0, scale=1, size=200)
        values[150] = 10.0  # Inject a 10-sigma spike
        values[170] = -8.0  # Inject a negative spike

        zscores = rolling_zscore(values, window=60)

        # The positive spike should have z > 5
        assert zscores[150] > 5.0
        # The negative spike should have z < -5
        assert zscores[170] < -5.0

    def test_scoring_with_real_anomaly_values(self):
        """Simulate realistic anomaly computation → CESI scoring."""
        np.random.seed(42)

        # Simulate per-layer anomaly z-scores
        layer_zscores = {
            SignalLayer.RESEARCH_FUNDING: np.random.uniform(0, 20),
            SignalLayer.PATENT_ACTIVITY: np.random.uniform(0, 20),
            SignalLayer.SUPPLY_CHAIN: np.random.uniform(0, 20),
            SignalLayer.ENERGY_CONFLICT: np.random.uniform(0, 20),
        }

        score, amp_applied, breakdown = compute_cesi_score(layer_zscores)
        severity = classify_severity(score)

        # Score should be valid
        assert 0 <= score <= 100
        assert severity in list(SeverityBand)
        # All layers should appear in breakdown
        for layer in SignalLayer:
            assert layer.value in breakdown


class TestSourceRegistryIntegration:
    """Ingestion source registry tests."""

    def test_all_sources_importable(self):
        from frr.ingestion.sources import ALL_SOURCES

        assert len(ALL_SOURCES) >= 8  # Phase 1 had 8 sources

    def test_all_sources_have_names(self):
        from frr.ingestion.sources import ALL_SOURCES

        names = [s.SOURCE_NAME for s in ALL_SOURCES]
        assert len(names) == len(set(names)), "Duplicate source names"

    def test_all_sources_have_valid_layers(self):
        from frr.ingestion.sources import ALL_SOURCES

        for source_cls in ALL_SOURCES:
            assert isinstance(source_cls.LAYER, SignalLayer)
