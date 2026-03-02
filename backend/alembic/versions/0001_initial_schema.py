"""Initial schema — all FRR tables.

Revision ID: 0001_initial_schema
Revises: -
Create Date: 2024-12-01 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────
    signal_layer = sa.Enum(
        "research_funding", "patent_activity", "supply_chain", "energy_conflict",
        name="signal_layer",
    )
    crisis_type = sa.Enum(
        "recession", "currency_crisis", "sovereign_default", "banking_crisis", "political_unrest",
        name="crisis_type",
    )
    severity_band = sa.Enum(
        "stable", "elevated", "concerning", "high_risk", "critical",
        name="severity_band",
    )
    user_role = sa.Enum(
        "viewer", "analyst", "admin", "super_admin",
        name="user_role",
    )
    alert_channel = sa.Enum(
        "email", "slack", "webhook", "websocket",
        name="alert_channel",
    )
    report_format = sa.Enum("pdf", "html", name="report_format")
    drift_type = sa.Enum(
        "data_drift", "prediction_drift", "feature_importance",
        name="drift_type",
    )

    signal_layer.create(op.get_bind())
    crisis_type.create(op.get_bind())
    severity_band.create(op.get_bind())
    user_role.create(op.get_bind())
    alert_channel.create(op.get_bind())
    report_format.create(op.get_bind())
    drift_type.create(op.get_bind())

    # ── Organizations ──────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(256), unique=True, nullable=False),
        sa.Column("slug", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("allowed_regions", JSONB, server_default="[]"),
        sa.Column("settings", JSONB, server_default="{}"),
        sa.Column("tier", sa.String(32), server_default="'professional'"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── Regions ────────────────────────────────────────────────────────
    op.create_table(
        "regions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("iso_codes", JSONB, server_default="{}"),
        sa.Column("centroid_lat", sa.Float, nullable=False),
        sa.Column("centroid_lon", sa.Float, nullable=False),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── Signal Series ──────────────────────────────────────────────────
    op.create_table(
        "signal_series",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("region_id", UUID(as_uuid=True), sa.ForeignKey("regions.id"), nullable=False),
        sa.Column("layer", signal_layer, nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("indicator", sa.String(128), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("metadata", JSONB, server_default="{}"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("region_id", "source", "indicator", "ts", name="uq_signal_natural_key"),
        sa.Index("ix_signal_region_ts", "region_id", "ts"),
        sa.Index("ix_signal_layer", "layer"),
    )

    # ── Anomaly Scores ─────────────────────────────────────────────────
    op.create_table(
        "anomaly_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", UUID(as_uuid=True), sa.ForeignKey("signal_series.id"), nullable=False),
        sa.Column("region_id", UUID(as_uuid=True), sa.ForeignKey("regions.id"), nullable=False),
        sa.Column("layer", signal_layer),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("zscore", sa.Float, nullable=False),
        sa.Column("is_anomaly", sa.Boolean, server_default="false"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("ix_anomaly_region_ts", "region_id", "ts"),
    )

    # ── Predictions ────────────────────────────────────────────────────
    op.create_table(
        "predictions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("region_id", UUID(as_uuid=True), sa.ForeignKey("regions.id"), nullable=False),
        sa.Column("crisis_type", crisis_type, nullable=False),
        sa.Column("probability", sa.Float, nullable=False),
        sa.Column("confidence_lower", sa.Float, nullable=False),
        sa.Column("confidence_upper", sa.Float, nullable=False),
        sa.Column("horizon_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("explanation", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("ix_pred_region_horizon", "region_id", "horizon_date"),
    )

    # ── CESI Scores ────────────────────────────────────────────────────
    op.create_table(
        "cesi_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("region_id", UUID(as_uuid=True), sa.ForeignKey("regions.id"), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("severity", severity_band, nullable=False),
        sa.Column("layer_scores", JSONB, server_default="{}"),
        sa.Column("crisis_probabilities", JSONB, server_default="{}"),
        sa.Column("amplification_applied", sa.Boolean, server_default="false"),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("ix_cesi_region_ts", "region_id", "scored_at"),
    )

    # ── Crisis Labels ──────────────────────────────────────────────────
    op.create_table(
        "crisis_labels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("region_id", UUID(as_uuid=True), sa.ForeignKey("regions.id"), nullable=False),
        sa.Column("crisis_type", crisis_type),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.Float, server_default="1.0"),
        sa.Column("source", sa.String(128)),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("region_id", "crisis_type", "event_date", name="uq_crisis_label"),
    )

    # ── Audit Log ──────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(128), nullable=False, server_default="'system'"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(64)),
        sa.Column("resource_id", sa.String(128)),
        sa.Column("entity_type", sa.String(64)),
        sa.Column("entity_id", sa.String(128)),
        sa.Column("detail", JSONB, server_default="{}"),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("ix_audit_ts", "ts"),
    )

    # ── Users ──────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(256), nullable=False),
        sa.Column("full_name", sa.String(256)),
        sa.Column("role", user_role, nullable=False, server_default="'viewer'"),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("is_admin", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_login", sa.DateTime(timezone=True)),
    )

    # ── API Keys ───────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("key_hash", sa.String(256), nullable=False),
        sa.Column("scopes", JSONB, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Index("ix_apikey_key_hash", "key_hash"),
    )

    # ── Alert Rules ────────────────────────────────────────────────────
    op.create_table(
        "alert_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("region_code", sa.String(32)),
        sa.Column("crisis_type", crisis_type),
        sa.Column("metric", sa.String(32), nullable=False, server_default="'cesi_score'"),
        sa.Column("operator", sa.String(8), nullable=False, server_default="'>='"),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("channel", alert_channel, nullable=False, server_default="'websocket'"),
        sa.Column("channel_config", JSONB, server_default="{}"),
        sa.Column("cooldown_minutes", sa.Integer, server_default="60"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_fired_at", sa.DateTime(timezone=True)),
    )

    # ── Alert History ──────────────────────────────────────────────────
    op.create_table(
        "alert_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", UUID(as_uuid=True), sa.ForeignKey("alert_rules.id"), nullable=False),
        sa.Column("region_code", sa.String(32), nullable=False),
        sa.Column("metric_value", sa.Float, nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("channel", alert_channel),
        sa.Column("delivered", sa.Boolean, server_default="false"),
        sa.Column("delivery_error", sa.Text),
        sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("ix_alert_history_ts", "fired_at"),
    )

    # ── Drift Snapshots ────────────────────────────────────────────────
    op.create_table(
        "drift_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("drift_type", drift_type, nullable=False),
        sa.Column("region_code", sa.String(32)),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("alert_triggered", sa.Boolean, server_default="false"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Index("ix_drift_ts", "computed_at"),
    )

    # ── Report Jobs ────────────────────────────────────────────────────
    op.create_table(
        "report_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("region_code", sa.String(32)),
        sa.Column("report_format", report_format, nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), server_default="'pending'"),
        sa.Column("file_path", sa.String(512)),
        sa.Column("file_size_bytes", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    # ── TimescaleDB hypertables ────────────────────────────────────────
    op.execute("SELECT create_hypertable('signal_series', 'ts', if_not_exists => TRUE)")
    op.execute("SELECT create_hypertable('anomaly_scores', 'ts', if_not_exists => TRUE)")


def downgrade() -> None:
    tables = [
        "report_jobs", "drift_snapshots", "alert_history", "alert_rules",
        "api_keys", "users", "audit_log", "crisis_labels", "cesi_scores",
        "predictions", "anomaly_scores", "signal_series", "regions", "organizations",
    ]
    for table in tables:
        op.drop_table(table)

    for enum_name in [
        "drift_type", "report_format", "alert_channel",
        "user_role", "severity_band", "crisis_type", "signal_layer",
    ]:
        sa.Enum(name=enum_name).drop(op.get_bind())
