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
    role: str = "viewer"
    organization_id: uuid.UUID | None = None
    is_active: bool
    is_admin: bool
    created_at: datetime


# ── Organization ───────────────────────────────────────────────────────

class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=256)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9\-]+$")
    allowed_regions: list[str] = Field(default_factory=list, description="Empty = all regions")
    tier: str = "open"


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    allowed_regions: list[str]
    tier: str
    is_active: bool
    created_at: datetime


class OrganizationUpdate(BaseModel):
    name: str | None = None
    allowed_regions: list[str] | None = None
    tier: str | None = None
    is_active: bool | None = None


# ── API Key ────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["read:cesi", "read:signals"])
    expires_in_days: int | None = Field(default=365, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class ApiKeyCreated(BaseModel):
    """Returned only once — the raw key is shown only at creation."""
    key: str
    detail: ApiKeyOut


# ── Alert Rule ─────────────────────────────────────────────────────────

class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    region_code: str | None = None
    crisis_type: str | None = None
    metric: str = "cesi_score"
    operator: str = ">="
    threshold: float = Field(ge=0, le=100)
    channel: str = "websocket"
    channel_config: dict = Field(default_factory=dict)
    cooldown_minutes: int = Field(default=60, ge=1)


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    threshold: float | None = None
    channel: str | None = None
    channel_config: dict | None = None
    cooldown_minutes: int | None = None
    is_active: bool | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    region_code: str | None = None
    crisis_type: str | None = None
    metric: str
    operator: str
    threshold: float
    channel: str
    channel_config: dict
    cooldown_minutes: int
    is_active: bool
    created_at: datetime
    last_fired_at: datetime | None = None


class AlertHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    region_code: str
    metric_value: float
    threshold: float
    message: str
    channel: str
    delivered: bool
    delivery_error: str | None = None
    fired_at: datetime


# ── Report ─────────────────────────────────────────────────────────────

class ReportJobCreate(BaseModel):
    region_code: str | None = None
    report_format: str = "pdf"
    period_start: datetime
    period_end: datetime


class ReportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    region_code: str | None = None
    report_format: str
    period_start: datetime
    period_end: datetime
    status: str
    file_path: str | None = None
    file_size_bytes: int | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


# ── Drift / Model Monitoring ──────────────────────────────────────────

class DriftSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    drift_type: str
    region_code: str | None = None
    model_version: str
    metrics: dict
    alert_triggered: bool
    computed_at: datetime


# ── SHAP Explainability ───────────────────────────────────────────────

class SHAPExplanation(BaseModel):
    region_code: str
    crisis_type: str | None = None
    top_features: list[dict]
    shap_values: dict
    base_value: float
    model_version: str
    computed_at: datetime


# ── NLP / News ─────────────────────────────────────────────────────────

class NewsSignalOut(BaseModel):
    title: str
    source_url: str
    region_code: str
    classification: str
    confidence: float
    sentiment: float
    published_at: datetime
    processed_at: datetime


class NLPScanResult(BaseModel):
    articles_scanned: int
    signals_extracted: int
    region_breakdown: dict[str, int]


# ── Audit ──────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None = None
    action: str
    resource: str
    resource_id: str | None = None
    detail: dict
    ip_address: str | None = None
    created_at: datetime
