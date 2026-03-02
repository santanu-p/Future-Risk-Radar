"""Tests for the GAT model module."""

from __future__ import annotations

import pytest
import torch

from frr.models.gat import MVP_REGION_CODES, SIGNAL_LAYERS, _TRADE_DEPENDENCY


class TestGATConfig:
    """Graph structure configuration constants."""

    def test_mvp_region_codes(self):
        assert len(MVP_REGION_CODES) >= 5
        assert "EU" in MVP_REGION_CODES
        assert "MENA" in MVP_REGION_CODES
        assert "EAST_ASIA" in MVP_REGION_CODES

    def test_signal_layers(self):
        assert len(SIGNAL_LAYERS) == 4
        assert "research_funding" in SIGNAL_LAYERS
        assert "patent_activity" in SIGNAL_LAYERS
        assert "supply_chain" in SIGNAL_LAYERS
        assert "energy_conflict" in SIGNAL_LAYERS

    def test_trade_dependency_shape(self):
        """Trade dependency matrix: n_regions × n_regions."""
        n = len(MVP_REGION_CODES)
        assert len(_TRADE_DEPENDENCY) == n
        for row in _TRADE_DEPENDENCY:
            assert len(row) == n

    def test_trade_dependency_diagonal_zero(self):
        """Self-trade is always 0."""
        for i, row in enumerate(_TRADE_DEPENDENCY):
            assert row[i] == 0.0


class TestCrisisLSTMImport:
    """Verify LSTM model can be imported."""

    def test_import(self):
        from frr.models.lstm import CrisisLSTM

        model = CrisisLSTM(input_dim=64, hidden_dim=32, num_layers=1, num_crisis_types=5)
        assert model is not None

    def test_forward_shape(self):
        from frr.models.lstm import CrisisLSTM

        model = CrisisLSTM(input_dim=64, hidden_dim=32, num_layers=1, num_crisis_types=5)
        model.eval()
        # Batch of 2, sequence length 12, 64 features
        x = torch.randn(2, 12, 64)
        with torch.no_grad():
            output = model(x)
        # Output shape: (batch_size, num_crisis_types)
        assert output.shape == (2, 5)

    def test_output_probabilities(self):
        from frr.models.lstm import CrisisLSTM

        model = CrisisLSTM(input_dim=64, hidden_dim=32, num_layers=1, num_crisis_types=5)
        model.eval()
        x = torch.randn(1, 12, 64)
        with torch.no_grad():
            output = model(x)
        # Sigmoid output → all values in [0, 1]
        assert (output >= 0).all()
        assert (output <= 1).all()
