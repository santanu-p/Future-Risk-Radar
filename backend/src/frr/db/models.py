"""SQLAlchemy ORM models — TimescaleDB hypertables + relational tables.

Table Hierarchy
===============
- Region          — geographic/economic blocs (EU, MENA, …)
- SignalSeries    — raw time-series from ingestion (one row per source × date × region)
- AnomalyScore   — z-score anomaly per signal
- Prediction      — model forecasts per region × crisis type
- CESIScore       — composite CESI output per region per run
- CrisisLabel     — ground-truth labels for supervised training
- AuditLog        — change tracking for compliance
- User            — auth accounts (MVP: simple JWT)
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
    actor: Mapped[str] = mapped_column(String(128), nullable=False, doc="user email or 'system'")
    action: Mapped[str] = mapped_column(String(64), nullable=False, doc="e.g. ingest, score, login")
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── User ───────────────────────────────────────────────────────────────

class User(Base):
    """Application user for JWT auth (MVP: simple local accounts)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
