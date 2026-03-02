"""Tests for exception hierarchy."""

from __future__ import annotations

from frr.exceptions import (
    AuthError,
    DatabaseError,
    FRRError,
    IngestionError,
    ModelError,
    NotFoundError,
    RateLimitError,
    ScoringError,
)


class TestExceptionHierarchy:
    """All custom exceptions inherit from FRRError."""

    def test_frr_error_base(self):
        e = FRRError("test", code="TEST_CODE")
        assert str(e) == "test"
        assert e.code == "TEST_CODE"

    def test_frr_error_defaults(self):
        e = FRRError()
        assert e.code == "FRR_ERROR"

    def test_ingestion_error(self):
        e = IngestionError("FRED", "timeout")
        assert "FRED" in str(e)
        assert "timeout" in str(e)
        assert e.source == "FRED"
        assert e.code == "INGESTION_ERROR"
        assert isinstance(e, FRRError)

    def test_rate_limit_error(self):
        e = RateLimitError("EIA", retry_after=60)
        assert e.retry_after == 60
        assert isinstance(e, IngestionError)
        assert isinstance(e, FRRError)

    def test_rate_limit_no_retry_after(self):
        e = RateLimitError("EIA")
        assert e.retry_after is None

    def test_database_error(self):
        e = DatabaseError("connection lost")
        assert "connection lost" in str(e)
        assert e.code == "DB_ERROR"

    def test_not_found_error(self):
        e = NotFoundError("Region", "EU")
        assert "Region" in str(e)
        assert "EU" in str(e)
        assert e.entity == "Region"
        assert e.identifier == "EU"
        assert e.code == "NOT_FOUND"

    def test_model_error(self):
        e = ModelError("training diverged")
        assert e.code == "MODEL_ERROR"
        assert isinstance(e, FRRError)

    def test_scoring_error(self):
        e = ScoringError("missing layers")
        assert e.code == "SCORING_ERROR"
        assert isinstance(e, FRRError)

    def test_auth_error(self):
        e = AuthError()
        assert e.code == "AUTH_ERROR"
        assert "Authentication failed" in str(e)

    def test_auth_error_custom_message(self):
        e = AuthError("token expired")
        assert "token expired" in str(e)
