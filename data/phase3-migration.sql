-- ── Future Risk Radar — Phase 3 Migration ─────────────────────────────
-- Adds: organizations, api_keys, alert_rules, alert_history,
--        drift_snapshots, report_jobs, and expands regions to 16.
-- Updates: users table with role + organization FK

-- ── New Enum Types ────────────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('viewer', 'analyst', 'admin', 'super_admin');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE alert_channel AS ENUM ('email', 'slack', 'webhook', 'websocket');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE report_format AS ENUM ('pdf', 'html');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE drift_type AS ENUM ('data_drift', 'prediction_drift', 'feature_importance');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── Organizations ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(256) NOT NULL,
    slug            VARCHAR(64) UNIQUE NOT NULL,
    allowed_regions JSONB DEFAULT '[]',
    settings        JSONB DEFAULT '{}',
    tier            VARCHAR(32) DEFAULT 'open',
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_org_slug ON organizations(slug);

-- ── Users — add role + organization FK ────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS role user_role DEFAULT 'viewer';
ALTER TABLE users ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id);

-- ── API Keys ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name            VARCHAR(128) NOT NULL,
    key_prefix      VARCHAR(12) NOT NULL,
    key_hash        VARCHAR(256) NOT NULL,
    scopes          JSONB DEFAULT '[]',
    expires_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    created_by      UUID REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS ix_apikey_key_hash ON api_keys(key_hash);

-- ── Alert Rules ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_rules (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id),
    created_by      UUID REFERENCES users(id),
    name            VARCHAR(256) NOT NULL,
    description     TEXT,
    region_code     VARCHAR(32),
    crisis_type     crisis_type,
    metric          VARCHAR(32) NOT NULL DEFAULT 'cesi_score',
    operator        VARCHAR(8) NOT NULL DEFAULT '>=',
    threshold       DOUBLE PRECISION NOT NULL,
    channel         alert_channel NOT NULL DEFAULT 'websocket',
    channel_config  JSONB DEFAULT '{}',
    cooldown_minutes INTEGER DEFAULT 60,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_fired_at   TIMESTAMPTZ
);

-- ── Alert History ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_history (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id        UUID NOT NULL REFERENCES alert_rules(id),
    region_code    VARCHAR(32) NOT NULL,
    metric_value   DOUBLE PRECISION NOT NULL,
    threshold      DOUBLE PRECISION NOT NULL,
    message        TEXT NOT NULL,
    channel        alert_channel NOT NULL,
    delivered      BOOLEAN DEFAULT FALSE,
    delivery_error TEXT,
    fired_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_alert_history_ts ON alert_history(fired_at);

-- ── Drift Snapshots (model monitoring) ────────────────────────────────
CREATE TABLE IF NOT EXISTS drift_snapshots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    drift_type      drift_type NOT NULL,
    region_code     VARCHAR(32),
    model_version   VARCHAR(64) NOT NULL,
    metrics         JSONB NOT NULL,
    alert_triggered BOOLEAN DEFAULT FALSE,
    computed_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_drift_ts ON drift_snapshots(computed_at);

-- ── Report Jobs ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS report_jobs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id),
    region_code     VARCHAR(32),
    report_format   report_format NOT NULL,
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    status          VARCHAR(32) DEFAULT 'pending',
    file_path       VARCHAR(512),
    file_size_bytes INTEGER,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- ── Update Audit Log for Phase 3 schema ───────────────────────────────
-- The ORM now manages a richer audit_log table. Add missing columns if needed.
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS resource VARCHAR(64);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS resource_id VARCHAR(128);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address VARCHAR(45);

-- ── Expand Regions to 16 ─────────────────────────────────────────────
-- Upsert: insert new regions, skip existing ones
INSERT INTO regions (code, name, description, iso_codes, centroid_lat, centroid_lon) VALUES
    ('EU', 'European Union', 'EU-27 member bloc', '{"iso2": ["DE","FR","IT","ES","NL","BE","AT","IE","FI","PT","GR","SE","DK","PL","CZ","RO","BG","HR","SK","SI","LT","LV","EE","LU","MT","CY","HU"]}', 50.85, 4.35),
    ('MENA', 'Middle East & North Africa', 'MENA region including Gulf states', '{"iso2": ["SA","AE","EG","IR","IQ","IL","JO","LB","KW","QA","BH","OM","YE","SY","LY","TN","MA","DZ"]}', 29.0, 41.0),
    ('EAST_ASIA', 'East Asia', 'China, Japan, South Korea, Taiwan', '{"iso2": ["CN","JP","KR","TW","MN","HK","MO"]}', 35.0, 120.0),
    ('SOUTH_ASIA', 'South Asia', 'India sub-continent', '{"iso2": ["IN","PK","BD","LK","NP","AF","BT","MV"]}', 20.0, 78.0),
    ('LATAM', 'Latin America', 'Central and South America combined', '{"iso2": ["BR","MX","AR","CO","CL","PE","VE","EC","BO","PY","UY"]}', -15.0, -60.0),
    ('NORTH_AMERICA', 'North America', 'United States, Canada, Mexico', '{"iso2": ["US","CA","MX"]}', 40.0, -100.0),
    ('SUB_SAHARAN_AFRICA', 'Sub-Saharan Africa', 'Africa south of the Sahara', '{"iso2": ["NG","KE","ZA","ET","GH","TZ","UG","CM","SN","CI"]}', 0.0, 25.0),
    ('SOUTHEAST_ASIA', 'Southeast Asia', 'ASEAN region', '{"iso2": ["ID","TH","VN","PH","MY","SG","MM","KH","LA","BN"]}', 5.0, 110.0),
    ('CENTRAL_ASIA', 'Central Asia', 'Former Soviet Central Asian republics', '{"iso2": ["KZ","UZ","TM","KG","TJ"]}', 42.0, 65.0),
    ('OCEANIA', 'Oceania', 'Australia, New Zealand, Pacific Islands', '{"iso2": ["AU","NZ","FJ","PG","WS","TO","VU"]}', -25.0, 140.0),
    ('EASTERN_EUROPE', 'Eastern Europe', 'Non-EU Eastern Europe including Ukraine, Belarus', '{"iso2": ["UA","BY","MD","GE","AM","AZ","RS","BA","ME","MK","AL","XK"]}', 48.0, 30.0),
    ('NORDIC', 'Nordic Region', 'Nordic countries including non-EU members', '{"iso2": ["NO","IS","SE","DK","FI"]}', 63.0, 16.0),
    ('GULF_STATES', 'Gulf Cooperation Council', 'GCC member states', '{"iso2": ["SA","AE","KW","QA","BH","OM"]}', 24.0, 50.0),
    ('CARIBBEAN', 'Caribbean', 'Caribbean island nations', '{"iso2": ["CU","DO","JM","HT","TT","BB","BS","GY","SR"]}', 18.0, -72.0),
    ('CENTRAL_AMERICA', 'Central America', 'Central American nations', '{"iso2": ["GT","HN","SV","NI","CR","PA","BZ"]}', 14.0, -87.0),
    ('SOUTHERN_AFRICA', 'Southern Africa', 'SADC region', '{"iso2": ["ZA","BW","NA","ZW","MZ","ZM","MW","AO","SZ","LS"]}', -22.0, 28.0)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    iso_codes = EXCLUDED.iso_codes,
    centroid_lat = EXCLUDED.centroid_lat,
    centroid_lon = EXCLUDED.centroid_lon;

-- Done
DO $$ BEGIN RAISE NOTICE 'Phase 3 migration applied successfully'; END $$;
