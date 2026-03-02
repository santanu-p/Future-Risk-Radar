"""Tests for Pydantic API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from frr.api.schemas import (
    CESIHistoryPoint,
    CESIScoreOut,
    HealthResponse,
    PredictionOut,
    RegionOut,
    RegionSummary,
    SignalOut,
    SignalTimeSeries,
    SignalTimeSeriesPoint,
)


class TestHealthResponseSchema:
    def test_creation(self):
        hr = HealthResponse(status="ok", version="v1", environment="dev")
        assert hr.status == "ok"
        assert hr.version == "v1"


class TestRegionSchemas:
    def test_region_out(self):
        r = RegionOut(
            id=uuid.uuid4(),
            code="EU",
            name="European Union",
            iso_codes={"DE": "Germany", "FR": "France"},
            centroid_lat=50.1,
            centroid_lon=9.7,
            active=True,
            created_at=datetime.now(),
        )
        assert r.code == "EU"
        assert r.active is True

    def test_region_summary(self):
        r = RegionSummary(
            id=uuid.uuid4(),
            code="MENA",
            name="Middle East & North Africa",
            centroid_lat=29.0,
            centroid_lon=41.0,
            latest_cesi=45.5,
            severity="concerning",
        )
        assert r.latest_cesi == 45.5


class TestSignalSchemas:
    def test_signal_out(self):
        s = SignalOut(
            id=uuid.uuid4(),
            region_id=uuid.uuid4(),
            layer="energy_conflict",
            source="EIA",
            indicator="BRENT_CRUDE",
            ts=datetime.now(),
            value=85.5,
            ingested_at=datetime.now(),
        )
        assert s.value == 85.5

    def test_timeseries_point(self):
        p = SignalTimeSeriesPoint(ts=datetime.now(), value=42.0, zscore=2.5, is_anomaly=True)
        assert p.is_anomaly is True

    def test_timeseries_point_defaults(self):
        p = SignalTimeSeriesPoint(ts=datetime.now(), value=42.0)
        assert p.zscore is None
        assert p.is_anomaly is False

    def test_signal_timeseries(self):
        ts = SignalTimeSeries(
            region_code="EU",
            source="FRED",
            indicator="GDP",
            layer="supply_chain",
            data=[
                SignalTimeSeriesPoint(ts=datetime(2024, 1, 1), value=1.0),
                SignalTimeSeriesPoint(ts=datetime(2024, 2, 1), value=2.0),
            ],
        )
        assert len(ts.data) == 2


class TestPredictionSchema:
    def test_prediction_out(self):
        p = PredictionOut(
            id=uuid.uuid4(),
            region_id=uuid.uuid4(),
            crisis_type="recession",
            probability=0.75,
            confidence_lower=0.6,
            confidence_upper=0.85,
            horizon_date=datetime(2025, 1, 1),
            model_version="v0.1.0",
            explanation={"top_features": ["oil_price", "trade_vol"]},
            created_at=datetime.now(),
        )
        assert p.probability == 0.75


class TestCESISchemas:
    def test_cesi_score_out(self):
        c = CESIScoreOut(
            id=uuid.uuid4(),
            region_id=uuid.uuid4(),
            score=55.0,
            severity="concerning",
            layer_scores={"energy_conflict": 70, "supply_chain": 40},
            crisis_probabilities={"recession": 0.3},
            amplification_applied=False,
            model_version="v0.1.0",
            scored_at=datetime.now(),
        )
        assert c.score == 55.0
        assert c.amplification_applied is False

    def test_cesi_score_validation(self):
        """Score must be 0–100."""
        with pytest.raises(Exception):
            CESIScoreOut(
                id=uuid.uuid4(),
                region_id=uuid.uuid4(),
                score=150.0,  # > 100 → validation error
                severity="critical",
                layer_scores={},
                crisis_probabilities={},
                amplification_applied=False,
                model_version="v0.1.0",
                scored_at=datetime.now(),
            )

    def test_cesi_history_point(self):
        h = CESIHistoryPoint(score=42.0, severity="elevated", scored_at=datetime.now())
        assert h.score == 42.0
