"""Shared pytest fixtures for the FRR test suite."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure test settings are applied before any app import
os.environ.setdefault("FRR_ENVIRONMENT", "dev")
os.environ.setdefault("FRR_DB_HOST", "localhost")
os.environ.setdefault("FRR_DB_NAME", "frr_test")
os.environ.setdefault("FRR_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("FRR_JWT_SECRET", "test-secret-key-do-not-use-in-prod")

from frr.config import Settings  # noqa: E402
from frr.main import create_app  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    """Return a test Settings instance with defaults overridden."""
    return Settings(
        environment="dev",
        debug=True,
        db_host="localhost",
        db_name="frr_test",
        redis_url="redis://localhost:6379/1",
        jwt_secret="test-secret-key-do-not-use-in-prod",
        fred_api_key="test-fred-key",
        eia_api_key="test-eia-key",
        acled_api_key="test-acled-key",
        acled_email="test@test.com",
    )


@pytest.fixture
def app():
    """Create a fresh FastAPI app for each test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async test client — no real server needed."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_db_session():
    """Create a mock async SQLAlchemy session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.add = MagicMock()
    return session
