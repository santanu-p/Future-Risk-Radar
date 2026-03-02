"""Application configuration — loaded from environment variables with Pydantic Settings.

All secrets and tunables are defined here with sensible defaults for local development.
Production overrides via .env or environment variables.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Central configuration for all FRR services.

    Reads from environment variables (prefix ``FRR_``) and ``.env`` files.
    """

    model_config = SettingsConfigDict(
        env_prefix="FRR_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── General ────────────────────────────────────────────────────────
    environment: Environment = Environment.DEV
    debug: bool = True
    log_level: str = "INFO"
    app_name: str = "Future Risk Radar"
    api_version: str = "v1"

    # ── Server ─────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # ── Database (TimescaleDB / PostgreSQL) ─────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "frr"
    db_user: str = "frr"
    db_password: SecretStr = SecretStr("frr_dev_password")
    db_pool_size: int = 20
    db_pool_overflow: int = 10

    @property
    def database_url(self) -> str:
        pw = self.db_password.get_secret_value()
        return f"postgresql+asyncpg://{self.db_user}:{pw}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def database_url_sync(self) -> str:
        pw = self.db_password.get_secret_value()
        return f"postgresql://{self.db_user}:{pw}@{self.db_host}:{self.db_port}/{self.db_name}"

    # ── Redis ──────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl: int = 300  # seconds

    # ── MinIO / S3 ─────────────────────────────────────────────────────
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket_raw: str = "frr-raw-signals"
    s3_bucket_models: str = "frr-models"
    s3_bucket_exports: str = "frr-exports"

    # ── MLflow ─────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "http://localhost:5000"

    # ── JWT Auth ───────────────────────────────────────────────────────
    jwt_secret: SecretStr = SecretStr("CHANGE_ME_IN_PRODUCTION")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ── External API Keys ──────────────────────────────────────────────
    fred_api_key: str = ""
    eia_api_key: str = ""
    acled_api_key: str = ""
    acled_email: str = ""
    ucdp_api_url: str = "https://ucdpapi.pcr.uu.se/api"
    uspto_api_url: str = "https://api.uspto.gov/api/v1"
    nsf_api_url: str = "https://api.nsf.gov/services/v1/awards.json"
    uncomtrade_api_url: str = "https://comtradeapi.worldbank.org/data/v1"
    gdelt_bigquery_project: str = ""
    gdelt_api_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    epo_consumer_key: str = ""
    epo_consumer_secret: SecretStr = SecretStr("")

    # ── Phase 2 API Keys ───────────────────────────────────────────────
    entsoe_api_key: str = ""
    wipo_api_url: str = "https://patentscope.wipo.int/search/en/search.jsf"
    sipri_data_url: str = "https://milex.sipri.org/sipri_milex/pages/download"
    wto_api_url: str = "https://api.wto.org/timeseries/v1"
    wto_api_key: str = ""
    freightos_use_fred_proxy: bool = True
    unhcr_api_url: str = "https://data.unhcr.org/population"

    # ── Ingestion ──────────────────────────────────────────────────────
    ingestion_interval_minutes: int = 60
    ingestion_batch_size: int = 1000
    ingestion_retry_attempts: int = 3
    ingestion_timeout_seconds: int = 30

    # ── Model ──────────────────────────────────────────────────────────
    model_lookback_months: int = 36
    model_forecast_horizon_months: int = 12
    model_gnn_embedding_dim: int = 64
    model_lstm_hidden_dim: int = 128
    model_lstm_num_layers: int = 2
    model_bayesian_num_samples: int = 2000
    model_bayesian_num_warmup: int = 1000

    # ── Scoring ────────────────────────────────────────────────────────
    cesi_amplification_gamma: float = 15.0
    cesi_spike_threshold: float = 0.6
    cesi_min_layers_for_amplification: int = 3
    zscore_anomaly_threshold: float = 2.0
    zscore_baseline_years: int = 5

    # ── Spatial Propagation (Layer 4) ──────────────────────────────────
    propagation_beta: float = 0.15
    propagation_damping: float = 0.6
    propagation_hops: int = 3
    propagation_spike_threshold: float = 40.0

    # ── Alerting ───────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: str = "alerts@futureriskradar.io"
    smtp_use_tls: bool = True
    slack_default_webhook_url: str = ""

    # ── Reports ────────────────────────────────────────────────────────
    reports_s3_bucket: str = "frr-reports"
    reports_retention_days: int = 90

    # ── Model Monitoring ───────────────────────────────────────────────
    drift_psi_threshold: float = 0.2
    drift_check_interval_hours: int = 24

    # ── SHAP Explainability ────────────────────────────────────────────
    shap_background_samples: int = 100
    shap_max_features: int = 20

    # ── NLP / GDELT ────────────────────────────────────────────────────
    gdelt_scan_interval_minutes: int = 60
    gdelt_max_articles_per_scan: int = 500
    nlp_classifier_model: str = "distilbert-base-uncased"
    nlp_confidence_threshold: float = 0.65

    # ── Regions ────────────────────────────────────────────────────────
    mvp_regions: list[str] = Field(
        default=[
            "EU",
            "MENA",
            "EAST_ASIA",
            "SOUTH_ASIA",
            "LATAM",
            "NORTH_AMERICA",
            "SUB_SAHARAN_AFRICA",
            "SOUTHEAST_ASIA",
            "CENTRAL_ASIA",
            "OCEANIA",
            "EASTERN_EUROPE",
            "NORDIC",
            "GULF_STATES",
            "CARIBBEAN",
            "CENTRAL_AMERICA",
            "SOUTHERN_AFRICA",
        ]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance — cached after first load."""
    return Settings()
