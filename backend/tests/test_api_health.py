"""Tests for health and API endpoint responses."""

from __future__ import annotations

import pytest


class TestHealthEndpoint:
    """GET /health — liveness check."""

    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "environment" in data

    async def test_health_has_version(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert data["version"] == "v1"

    async def test_health_has_environment(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert data["environment"] in ("dev", "staging", "production")
