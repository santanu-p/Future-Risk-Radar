"""SQLAlchemy ORM models — TimescaleDB hypertables + relational tables.

Table Hierarchy
===============
- Organization    — multi-tenant isolation boundary
- Region          — geographic/economic blocs (EU, MENA, …)
- SignalSeries    — raw time-series from ingestion (one row per source × date × region)
- AnomalyScore   — z-score anomaly per signal
- Prediction      — model forecasts per region × crisis type
- CESIScore       — composite CESI output per region per run
- CrisisLabel     — ground-truth labels for supervised training
- AuditLog        — change tracking for compliance
- User            — auth accounts with RBAC roles
- ApiKey          — long-lived API keys for programmatic access
- AlertRule       — configurable alert thresholds per region/crisis-type
- AlertHistory    — triggered alert records
- DriftSnapshot   — model monitoring / data drift snapshots
- ReportJob       — generated intelligence brief records
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all FRR tables."""

    type_annotation_map = {
        dict: JSONB,
    }


# ── Enumerations ───────────────────────────────────────────────────────

class SignalLayer(str, PyEnum):
    """The four structural signal layers of FRR."""
    RESEARCH_FUNDING = "research_funding"
    PATENT_ACTIVITY = "patent_activity"
    SUPPLY_CHAIN = "supply_chain"
    ENERGY_CONFLICT = "energy_conflict"


class CrisisType(str, PyEnum):
    """Academically-defined crisis categories (Reinhart-Rogoff / Laeven-Valencia)."""
    RECESSION = "recession"
    CURRENCY_CRISIS = "currency_crisis"
    SOVEREIGN_DEFAULT = "sovereign_default"
    BANKING_CRISIS = "banking_crisis"
    POLITICAL_UNREST = "political_unrest"


class SeverityBand(str, PyEnum):
    STABLE = "stable"              # 0–20
    ELEVATED = "elevated"          # 21–40
    CONCERNING = "concerning"      # 41–60
    HIGH_RISK = "high_risk"        # 61–80
    CRITICAL = "critical"          # 81–100


class UserRole(str, PyEnum):
    """Role-based access control levels."""
    VIEWER = "viewer"              # Read-only access
    ANALYST = "analyst"            # Read + export + alert config
    ADMIN = "admin"                # Full org-level management
    SUPER_ADMIN = "super_admin"    # System-wide (FRR staff only)


class AlertChannel(str, PyEnum):
    """Notification delivery channel for alert rules."""
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    WEBSOCKET = "websocket"


class ReportFormat(str, PyEnum):
    PDF = "pdf"
    HTML = "html"


class DriftType(str, PyEnum):
    DATA_DRIFT = "data_drift"
    PREDICTION_DRIFT = "prediction_drift"
    FEATURE_IMPORTANCE = "feature_importance"


# ── Organization (multi-tenant boundary) ──────────────────────────────

class Organization(Base):
    """Tenant isolation boundary — each org sees only its allowed regions."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    allowed_regions: Mapped[dict] = mapped_column(
        JSONB, default=list, doc="List of region codes this org can access; empty = all"
    )
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, doc="Org-level config overrides")
    tier: Mapped[str] = mapped_column(String(32), default="professional", doc="open|professional|enterprise")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    users: Mapped[list["User"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


# ── Region ─────────────────────────────────────────────────────────────

class Region(Base):
    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    iso_codes: Mapped[dict] = mapped_column(JSONB, default=dict, doc="ISO 3166-1 codes included in this region")
    centroid_lat: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_lon: Mapped[float] = mapped_column(Float, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    signals: Mapped[list["SignalSeries"]] = relationship(back_populates="region", cascade="all, delete-orphan")
    cesi_scores: Mapped[list["CESIScore"]] = relationship(back_populates="region", cascade="all, delete-orphan")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="region", cascade="all, delete-orphan")


# ── SignalSeries (TimescaleDB hypertable) ──────────────────────────────

class SignalSeries(Base):
    """Raw ingested signal — one row per (region, source, date).

    This table will be converted to a TimescaleDB hypertable partitioned on ``ts``.
    """

    __tablename__ = "signal_series"
    __table_args__ = (
        UniqueConstraint("region_id", "source", "indicator", "ts", name="uq_signal_natural_key"),
        Index("ix_signal_region_ts", "region_id", "ts"),
        Index("ix_signal_layer", "layer"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id"), nullable=False)
    layer: Mapped[SignalLayer] = mapped_column(Enum(SignalLayer, name="signal_layer"), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, doc="e.g. FRED, EIA, ACLED")
    indicator: Mapped[str] = mapped_column(String(128), nullable=False, doc="e.g. GDP_GROWTH, BRENT_CRUDE")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    region: Mapped["Region"] = relationship(back_populates="signals")


# ── AnomalyScore ──────────────────────────────────────────────────────

class AnomalyScore(Base):
    """Z-score anomaly detection output — computed from SignalSeries baselines."""

    __tablename__ = "anomaly_scores"
    __table_args__ = (
        Index("ix_anomaly_region_ts", "region_id", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("signal_series.id"), nullable=False)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id"), nullable=False)
    layer: Mapped[SignalLayer] = mapped_column(Enum(SignalLayer, name="signal_layer", create_type=False))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    zscore: Mapped[float] = mapped_column(Float, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Prediction ─────────────────────────────────────────────────────────

class Prediction(Base):
    """Model forecast output — probability per crisis type per region."""

    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_pred_region_horizon", "region_id", "horizon_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id"), nullable=False)
    crisis_type: Mapped[CrisisType] = mapped_column(Enum(CrisisType, name="crisis_type"), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False, doc="0.0–1.0")
    confidence_lower: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_upper: Mapped[float] = mapped_column(Float, nullable=False)
    horizon_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict, doc="SHAP / feature attributions")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    region: Mapped["Region"] = relationship(back_populates="predictions")


# ── CESIScore ──────────────────────────────────────────────────────────

class CESIScore(Base):
    """Composite Economic Stress Index — the single headline risk number per region."""

    __tablename__ = "cesi_scores"
    __table_args__ = (
        Index("ix_cesi_region_ts", "region_id", "scored_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, doc="0–100 CESI score")
    severity: Mapped[SeverityBand] = mapped_column(Enum(SeverityBand, name="severity_band"), nullable=False)
    layer_scores: Mapped[dict] = mapped_column(
        JSONB, default=dict, doc="Per-layer breakdown: {layer: {weighted_anomaly, raw_score}}"
    )
    crisis_probabilities: Mapped[dict] = mapped_column(
        JSONB, default=dict, doc="Per-crisis-type probability: {type: {p, ci_lower, ci_upper}}"
    )
    amplification_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    region: Mapped["Region"] = relationship(back_populates="cesi_scores")


# ── CrisisLabel (supervised ground-truth) ──────────────────────────────

class CrisisLabel(Base):
    """Ground-truth crisis labels for model training & back-testing."""

    __tablename__ = "crisis_labels"
    __table_args__ = (
        UniqueConstraint("region_id", "crisis_type", "event_date", name="uq_crisis_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regions.id"), nullable=False)
    crisis_type: Mapped[CrisisType] = mapped_column(Enum(CrisisType, name="crisis_type", create_type=False))
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[float] = mapped_column(Float, default=1.0, doc="Severity weight for loss function")
    source: Mapped[str] = mapped_column(String(128), doc="Citation / data source")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── AuditLog ──────────────────────────────────────────────────────────

class AuditLog(Base):
    """Immutable audit trail — who changed what, when."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_ts", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system", doc="user email or 'system'")
    action: Mapped[str] = mapped_column(String(64), nullable=False, doc="HTTP method or action name")
    resource: Mapped[str | None] = mapped_column(String(64), doc="Resource type e.g. 'regions', 'alerts'")
    resource_id: Mapped[str | None] = mapped_column(String(128), doc="UUID of affected resource")
    entity_type: Mapped[str | None] = mapped_column(String(64), doc="Legacy: maps to resource")
    entity_id: Mapped[str | None] = mapped_column(String(128), doc="Legacy: maps to resource_id")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── User ───────────────────────────────────────────────────────────────

class User(Base):
    """Application user with RBAC roles and organization membership."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(256))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.VIEWER, nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization | None"] = relationship(back_populates="users")


# ── ApiKey ─────────────────────────────────────────────────────────────

class ApiKey(Base):
    """Long-lived API keys for programmatic / M2M access."""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_apikey_key_hash", "key_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False, doc="Human-readable label")
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False, doc="First 8 chars for identification")
    key_hash: Mapped[str] = mapped_column(String(256), nullable=False, doc="SHA-256 hash of the full key")
    scopes: Mapped[dict] = mapped_column(JSONB, default=list, doc='e.g. ["read:cesi","read:signals"]')
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="api_keys")


# ── AlertRule ──────────────────────────────────────────────────────────

class AlertRule(Base):
    """Configurable alert threshold — fires when conditions are met."""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Condition
    region_code: Mapped[str | None] = mapped_column(String(32), doc="NULL = all regions")
    crisis_type: Mapped[CrisisType | None] = mapped_column(
        Enum(CrisisType, name="crisis_type", create_type=False), nullable=True
    )
    metric: Mapped[str] = mapped_column(
        String(32), nullable=False, default="cesi_score",
        doc="cesi_score | crisis_probability | anomaly_zscore"
    )
    operator: Mapped[str] = mapped_column(String(8), nullable=False, default=">=", doc=">= | <= | > | < | ==")
    threshold: Mapped[float] = mapped_column(Float, nullable=False)

    # Delivery
    channel: Mapped[AlertChannel] = mapped_column(
        Enum(AlertChannel, name="alert_channel"), nullable=False, default=AlertChannel.WEBSOCKET
    )
    channel_config: Mapped[dict] = mapped_column(
        JSONB, default=dict, doc='e.g. {"webhook_url":"..."} or {"slack_channel":"#alerts"}'
    )
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60, doc="Min minutes between re-fires")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    alerts_fired: Mapped[list["AlertHistory"]] = relationship(back_populates="rule", cascade="all, delete-orphan")


# ── AlertHistory ──────────────────────────────────────────────────────

class AlertHistory(Base):
    """Record of a triggered alert."""

    __tablename__ = "alert_history"
    __table_args__ = (
        Index("ix_alert_history_ts", "fired_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    region_code: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[AlertChannel] = mapped_column(
        Enum(AlertChannel, name="alert_channel", create_type=False), nullable=False
    )
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_error: Mapped[str | None] = mapped_column(Text)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped["AlertRule"] = relationship(back_populates="alerts_fired")


# ── DriftSnapshot (model monitoring) ──────────────────────────────────

class DriftSnapshot(Base):
    """Periodic snapshot of data drift, prediction drift, and feature importance."""

    __tablename__ = "drift_snapshots"
    __table_args__ = (
        Index("ix_drift_ts", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drift_type: Mapped[DriftType] = mapped_column(
        Enum(DriftType, name="drift_type"), nullable=False
    )
    region_code: Mapped[str | None] = mapped_column(String(32))
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, doc="PSI, KL divergence, wasserstein, etc."
    )
    alert_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── ReportJob ─────────────────────────────────────────────────────────

class ReportJob(Base):
    """Generated intelligence brief record."""

    __tablename__ = "report_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(32), doc="NULL = global report")
    report_format: Mapped[ReportFormat] = mapped_column(
        Enum(ReportFormat, name="report_format"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", doc="pending|generating|completed|failed")
    file_path: Mapped[str | None] = mapped_column(String(512), doc="S3/MinIO object key")
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
