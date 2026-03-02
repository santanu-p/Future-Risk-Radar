-- ── Future Risk Radar — TimescaleDB Initialization ────────────────────
-- This script runs on first container start via docker-entrypoint-initdb.d

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Enum Types ────────────────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE signal_layer AS ENUM (
        'research_funding',
        'patent_activity',
        'supply_chain',
        'energy_conflict'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE crisis_type AS ENUM (
        'recession',
        'currency_crisis',
        'sovereign_default',
        'banking_crisis',
        'political_unrest'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE severity_band AS ENUM (
        'stable',
        'elevated',
        'concerning',
        'high_risk',
        'critical'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── Regions ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS regions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code        VARCHAR(32) UNIQUE NOT NULL,
    name        VARCHAR(128) NOT NULL,
    description TEXT,
    iso_codes   JSONB DEFAULT '{}',
    centroid_lat DOUBLE PRECISION NOT NULL,
    centroid_lon DOUBLE PRECISION NOT NULL,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_regions_code ON regions(code);

-- ── Signal Series (hypertable) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_series (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id   UUID NOT NULL REFERENCES regions(id),
    layer       signal_layer NOT NULL,
    source      VARCHAR(64) NOT NULL,
    indicator   VARCHAR(128) NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    metadata    JSONB DEFAULT '{}',
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_signal_natural_key UNIQUE (region_id, source, indicator, ts)
);

-- Convert to TimescaleDB hypertable (partitioned by time)
SELECT create_hypertable('signal_series', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS ix_signal_region_ts ON signal_series(region_id, ts);
CREATE INDEX IF NOT EXISTS ix_signal_layer ON signal_series(layer);

-- ── Anomaly Scores ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomaly_scores (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    signal_id   UUID NOT NULL REFERENCES signal_series(id),
    region_id   UUID NOT NULL REFERENCES regions(id),
    layer       signal_layer,
    ts          TIMESTAMPTZ NOT NULL,
    zscore      DOUBLE PRECISION NOT NULL,
    is_anomaly  BOOLEAN DEFAULT FALSE,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('anomaly_scores', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS ix_anomaly_region_ts ON anomaly_scores(region_id, ts);

-- ── Predictions ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS predictions (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id         UUID NOT NULL REFERENCES regions(id),
    crisis_type       crisis_type NOT NULL,
    probability       DOUBLE PRECISION NOT NULL,
    confidence_lower  DOUBLE PRECISION NOT NULL,
    confidence_upper  DOUBLE PRECISION NOT NULL,
    horizon_date      TIMESTAMPTZ NOT NULL,
    model_version     VARCHAR(64) NOT NULL,
    explanation       JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pred_region_horizon ON predictions(region_id, horizon_date);

-- ── CESI Scores ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cesi_scores (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id             UUID NOT NULL REFERENCES regions(id),
    score                 DOUBLE PRECISION NOT NULL,
    severity              severity_band NOT NULL,
    layer_scores          JSONB DEFAULT '{}',
    crisis_probabilities  JSONB DEFAULT '{}',
    amplification_applied BOOLEAN DEFAULT FALSE,
    model_version         VARCHAR(64) NOT NULL,
    scored_at             TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('cesi_scores', 'scored_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS ix_cesi_region_ts ON cesi_scores(region_id, scored_at);

-- ── Crisis Labels (ground truth) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS crisis_labels (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id   UUID NOT NULL REFERENCES regions(id),
    crisis_type crisis_type NOT NULL,
    event_date  TIMESTAMPTZ NOT NULL,
    severity    DOUBLE PRECISION DEFAULT 1.0,
    source      VARCHAR(128),
    notes       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_crisis_label UNIQUE (region_id, crisis_type, event_date)
);

-- ── Audit Log ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    actor       VARCHAR(128) NOT NULL,
    action      VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64),
    entity_id   VARCHAR(128),
    detail      JSONB DEFAULT '{}',
    ts          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);

-- ── Users ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(256) UNIQUE NOT NULL,
    hashed_password VARCHAR(256) NOT NULL,
    full_name       VARCHAR(256),
    is_active       BOOLEAN DEFAULT TRUE,
    is_admin        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);

-- ── Continuous Aggregates (materialized views for fast queries) ───────
-- Hourly signal averages per region/layer
CREATE MATERIALIZED VIEW IF NOT EXISTS signal_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    region_id,
    layer,
    source,
    indicator,
    AVG(value) AS avg_value,
    MIN(value) AS min_value,
    MAX(value) AS max_value,
    COUNT(*) AS sample_count
FROM signal_series
GROUP BY bucket, region_id, layer, source, indicator
WITH NO DATA;

-- Daily CESI score summary
CREATE MATERIALIZED VIEW IF NOT EXISTS cesi_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', scored_at) AS bucket,
    region_id,
    AVG(score) AS avg_score,
    MAX(score) AS max_score,
    MIN(score) AS min_score
FROM cesi_scores
GROUP BY bucket, region_id
WITH NO DATA;

-- ── Refresh policies ──────────────────────────────────────────────────
SELECT add_continuous_aggregate_policy('signal_hourly',
    start_offset => INTERVAL '3 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT add_continuous_aggregate_policy('cesi_daily',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- ── Data retention policies ───────────────────────────────────────────
-- Keep raw signals for 3 years, anomaly scores for 2 years
SELECT add_retention_policy('signal_series', INTERVAL '3 years', if_not_exists => TRUE);
SELECT add_retention_policy('anomaly_scores', INTERVAL '2 years', if_not_exists => TRUE);

-- Done
DO $$ BEGIN RAISE NOTICE 'FRR database schema initialized successfully'; END $$;
