"""Tests for configuration and settings."""

from __future__ import annotations

import pytest

from frr.config import Environment, Settings


class TestSettings:
    """Pydantic settings validation."""

    def test_defaults(self):
        s = Settings()
        assert s.environment == Environment.DEV
        assert s.debug is True
        assert s.app_name == "Future Risk Radar"
        assert s.api_version == "v1"

    def test_database_url(self):
        s = Settings(db_user="u", db_password="p", db_host="h", db_port=5432, db_name="d")
        assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d"

    def test_database_url_sync(self):
        s = Settings(db_user="u", db_password="p", db_host="h", db_port=5432, db_name="d")
        assert s.database_url_sync == "postgresql://u:p@h:5432/d"

    def test_cors_origins_default(self):
        s = Settings()
        assert "http://localhost:5173" in s.cors_origins
        assert "http://localhost:3000" in s.cors_origins

    def test_mvp_regions(self):
        s = Settings()
        assert "EU" in s.mvp_regions
        assert "MENA" in s.mvp_regions
        assert len(s.mvp_regions) == 16

    def test_jwt_defaults(self):
        s = Settings()
        assert s.jwt_algorithm == "HS256"
        assert s.jwt_expire_minutes == 60

    def test_environment_enum(self):
        assert Environment.DEV.value == "dev"
        assert Environment.STAGING.value == "staging"
        assert Environment.PRODUCTION.value == "production"

    def test_ingestion_defaults(self):
        s = Settings()
        assert s.ingestion_interval_minutes == 60
        assert s.ingestion_batch_size == 1000
        assert s.ingestion_retry_attempts == 3
        assert s.ingestion_timeout_seconds == 30

    def test_scoring_defaults(self):
        s = Settings()
        assert s.cesi_amplification_gamma == 15.0
        assert s.cesi_spike_threshold == 0.6
        assert s.cesi_min_layers_for_amplification == 3
        assert s.zscore_anomaly_threshold == 2.0
        assert s.zscore_baseline_years == 5
