"""Pydantic v2 schemas — request/response models for the API layer.

All schemas use ``model_config = ConfigDict(from_attributes=True)`` so they
can be constructed directly from SQLAlchemy ORM instances.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Health ─────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str


# ── Region ─────────────────────────────────────────────────────────────

class RegionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    iso_codes: dict
    centroid_lat: float
    centroid_lon: float
    active: bool
    created_at: datetime


class RegionSummary(BaseModel):
    """Region + its latest CESI score (for dashboard list view)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    centroid_lat: float
    centroid_lon: float
    latest_cesi: float | None = None
    severity: str | None = None


# ── Signal ─────────────────────────────────────────────────────────────

class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    region_id: uuid.UUID
    layer: str
    source: str
    indicator: str
    ts: datetime
    value: float
    ingested_at: datetime


class SignalTimeSeriesPoint(BaseModel):
    ts: datetime
    value: float
    zscore: float | None = None
    is_anomaly: bool = False


class SignalTimeSeries(BaseModel):
    region_code: str
    source: str
    indicator: str
    layer: str
    data: list[SignalTimeSeriesPoint]


# ── Prediction ─────────────────────────────────────────────────────────

class PredictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    region_id: uuid.UUID
    crisis_type: str
    probability: float
    confidence_lower: float
    confidence_upper: float
    horizon_date: datetime
    model_version: str
    explanation: dict
    created_at: datetime


# ── CESI ───────────────────────────────────────────────────────────────

class CESIScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    region_id: uuid.UUID
    score: float = Field(ge=0, le=100)
    severity: str
    layer_scores: dict
    crisis_probabilities: dict
    amplification_applied: bool
    model_version: str
    scored_at: datetime


class CESIHistoryPoint(BaseModel):
    score: float
    severity: str
    scored_at: datetime


class CESIRegionDetail(BaseModel):
    """Full CESI detail for a single region — used by the dashboard detail view."""
    region: RegionOut
    current_score: CESIScoreOut | None = None
    history: list[CESIHistoryPoint] = []
    predictions: list[PredictionOut] = []


# ── Auth ───────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None = None
    is_active: bool
    is_admin: bool
    created_at: datetime
