"""Tests for the anomaly detection module — RollingWelford + rolling_zscore."""

from __future__ import annotations

import numpy as np
import pytest

from frr.models.anomaly import RollingWelford, detect_secondary_outliers, rolling_zscore


# ── RollingWelford ─────────────────────────────────────────────────────


class TestRollingWelford:
    """Numerically-stable rolling statistics."""

    def test_empty_state(self):
        rw = RollingWelford()
        assert rw.n == 0
        assert rw.mean == 0.0
        assert rw.variance == 0.0
        assert rw.std == 0.0

    def test_single_value(self):
        rw = RollingWelford()
        rw.add(5.0)
        assert rw.n == 1
        assert rw.mean == 5.0
        # variance undefined for n<2 => returns 0
        assert rw.variance == 0.0
        assert rw.std == 0.0

    def test_two_values(self):
        rw = RollingWelford()
        rw.add(2.0)
        rw.add(4.0)
        assert rw.n == 2
        assert rw.mean == pytest.approx(3.0)
        # sample variance = (2-3)^2 + (4-3)^2 / 1 = 2.0
        assert rw.variance == pytest.approx(2.0, rel=1e-9)
        assert rw.std == pytest.approx(np.sqrt(2.0), rel=1e-9)

    def test_known_sequence(self):
        rw = RollingWelford()
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        for v in data:
            rw.add(v)
        assert rw.n == 5
        assert rw.mean == pytest.approx(30.0)
        expected_var = np.var(data, ddof=1)
        assert rw.variance == pytest.approx(expected_var, rel=1e-9)
        assert rw.std == pytest.approx(np.std(data, ddof=1), rel=1e-9)

    def test_remove_returns_to_correct_state(self):
        rw = RollingWelford()
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        for v in data:
            rw.add(v)

        # Remove first value — should be like [20, 30, 40, 50]
        rw.remove(10.0)
        assert rw.n == 4
        remaining = [20.0, 30.0, 40.0, 50.0]
        assert rw.mean == pytest.approx(np.mean(remaining), rel=1e-6)
        assert rw.variance == pytest.approx(np.var(remaining, ddof=1), rel=1e-4)

    def test_remove_all_resets(self):
        rw = RollingWelford()
        rw.add(5.0)
        rw.remove(5.0)
        assert rw.n == 0
        assert rw.mean == 0.0
        assert rw.m2 == 0.0

    def test_add_remove_add_sequence(self):
        rw = RollingWelford()
        rw.add(1.0)
        rw.add(2.0)
        rw.add(3.0)
        rw.remove(1.0)
        rw.add(4.0)
        # Now contains [2, 3, 4]
        assert rw.n == 3
        assert rw.mean == pytest.approx(3.0, rel=1e-6)

    def test_constant_values_zero_variance(self):
        rw = RollingWelford()
        for _ in range(10):
            rw.add(42.0)
        assert rw.mean == pytest.approx(42.0)
        assert rw.variance == pytest.approx(0.0, abs=1e-10)

    def test_large_values_numerical_stability(self):
        """Welford should handle large values without overflow issues."""
        rw = RollingWelford()
        base = 1e9
        data = [base + i for i in range(100)]
        for v in data:
            rw.add(v)
        assert rw.mean == pytest.approx(np.mean(data), rel=1e-6)
        assert rw.variance == pytest.approx(np.var(data, ddof=1), rel=1e-4)


# ── rolling_zscore ─────────────────────────────────────────────────────


class TestRollingZscore:
    """Rolling z-score over numpy arrays."""

    def test_output_shape_matches_input(self):
        values = np.random.randn(100)
        result = rolling_zscore(values, window=30)
        assert result.shape == values.shape

    def test_first_window_elements_are_zero(self):
        values = np.ones(100)
        result = rolling_zscore(values, window=30)
        # First `window` elements should be 0 because no full window yet
        np.testing.assert_array_equal(result[:30], 0.0)

    def test_constant_values_zero_zscore(self):
        values = np.full(100, 42.0)
        result = rolling_zscore(values, window=30)
        # Constant → std=0 → z-scores stay 0
        np.testing.assert_array_almost_equal(result, 0.0)

    def test_spike_produces_high_zscore(self):
        values = np.ones(100)
        values[80] = 100.0  # Inject spike
        result = rolling_zscore(values, window=30)
        # The spike should have a very high z-score
        assert result[80] > 3.0

    def test_negative_spike(self):
        values = np.zeros(100)
        values[80] = -50.0
        result = rolling_zscore(values, window=30)
        # Negative spike → negative z-score (in context of zeros)
        # window of zeros → std ≈ 0, so z-score stays 0 (division guard)
        # Need some variance in the window
        values2 = np.random.randn(100)
        values2[80] = -50.0
        result2 = rolling_zscore(values2, window=30)
        assert result2[80] < -3.0

    def test_custom_window_size(self):
        values = np.random.randn(200)
        result = rolling_zscore(values, window=60)
        # First 60 elements should be zero
        np.testing.assert_array_equal(result[:60], 0.0)
        # After window, values should be computed
        assert not np.all(result[60:] == 0.0)


class TestSecondaryOutlierDetection:
    """IsolationForest + LOF composite detector."""

    def test_short_series_returns_no_outliers(self):
        values = np.random.randn(10)
        mask = detect_secondary_outliers(values)
        assert mask.shape == (10,)
        assert mask.dtype == np.bool_
        assert not mask.any()

    def test_detects_injected_outliers(self):
        np.random.seed(42)
        base = np.random.normal(0, 1, 120)
        base[30] = 8.5
        base[85] = -7.8
        mask = detect_secondary_outliers(base)
        assert mask.shape == (120,)
        assert mask[30] or mask[85]

    def test_accepts_2d_input(self):
        np.random.seed(42)
        values = np.random.normal(0, 1, (100, 1))
        values[50, 0] = 9.0
        mask = detect_secondary_outliers(values)
        assert mask.shape == (100,)
