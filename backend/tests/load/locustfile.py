"""Locust load tests for the FRR API.

Run with:
    locust -f tests/load/locustfile.py --host http://localhost:8000

Targets:
    - 1000 req/s sustained throughput
    - p99 latency < 200 ms
"""

from __future__ import annotations

import json
import random

from locust import HttpUser, between, tag, task


# MVP regions for parameterised requests
REGIONS = ["EU", "MENA", "EAST_ASIA", "SOUTH_ASIA", "LATAM"]


class FRRUser(HttpUser):
    """Simulates a typical FRR dashboard user browsing regions and scores."""

    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Authenticate and store token."""
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"email": "loadtest@frr.io", "password": "loadtest123"},
            name="/auth/login",
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token", "")
            self.client.headers.update({"Authorization": f"Bearer {token}"})
        # If login fails, continue without auth — health endpoints still work

    # ── Health check (high frequency) ──────────────────────────────────

    @tag("health")
    @task(10)
    def health_check(self):
        self.client.get("/health", name="/health")

    # ── Region endpoints ───────────────────────────────────────────────

    @tag("regions")
    @task(5)
    def list_regions(self):
        self.client.get("/api/v1/regions/", name="/regions/")

    @tag("regions")
    @task(3)
    def get_region(self):
        code = random.choice(REGIONS)
        self.client.get(f"/api/v1/regions/{code}", name="/regions/[code]")

    # ── CESI scores ────────────────────────────────────────────────────

    @tag("cesi")
    @task(5)
    def latest_scores(self):
        self.client.get("/api/v1/cesi/scores", name="/cesi/scores")

    @tag("cesi")
    @task(3)
    def region_detail(self):
        code = random.choice(REGIONS)
        self.client.get(f"/api/v1/cesi/{code}", name="/cesi/[code]")

    @tag("cesi")
    @task(2)
    def cesi_history(self):
        code = random.choice(REGIONS)
        self.client.get(
            f"/api/v1/cesi/{code}/history?limit=90",
            name="/cesi/[code]/history",
        )

    # ── Signals ────────────────────────────────────────────────────────

    @tag("signals")
    @task(2)
    def signal_timeseries(self):
        code = random.choice(REGIONS)
        self.client.get(
            f"/api/v1/signals/{code}/timeseries?source=FRED&indicator=GDP_GROWTH",
            name="/signals/[code]/timeseries",
        )

    # ── Alerts ─────────────────────────────────────────────────────────

    @tag("alerts")
    @task(2)
    def list_alerts(self):
        self.client.get("/api/v1/alerts/rules", name="/alerts/rules")

    @tag("alerts")
    @task(1)
    def alert_history(self):
        self.client.get(
            "/api/v1/alerts/history?limit=50",
            name="/alerts/history",
        )

    # ── Reports ────────────────────────────────────────────────────────

    @tag("reports")
    @task(1)
    def list_reports(self):
        self.client.get("/api/v1/reports?limit=20", name="/reports")

    # ── Monitoring / Drift ─────────────────────────────────────────────

    @tag("monitoring")
    @task(1)
    def model_health(self):
        self.client.get("/api/v1/monitoring/health", name="/monitoring/health")

    @tag("monitoring")
    @task(1)
    def drift_snapshots(self):
        self.client.get("/api/v1/monitoring/drift?limit=20", name="/monitoring/drift")

    # ── Explainability ─────────────────────────────────────────────────

    @tag("explain")
    @task(1)
    def explain(self):
        code = random.choice(REGIONS)
        self.client.get(f"/api/v1/explain/{code}", name="/explain/[code]")

    # ── NLP ────────────────────────────────────────────────────────────

    @tag("nlp")
    @task(1)
    def nlp_signals(self):
        self.client.get("/api/v1/nlp/signals?limit=50", name="/nlp/signals")

    @tag("nlp")
    @task(1)
    def nlp_summary(self):
        self.client.get("/api/v1/nlp/summary", name="/nlp/summary")

    # ── Training status (read-only) ────────────────────────────────────

    @tag("training")
    @task(1)
    def training_status(self):
        self.client.get("/api/v1/train/status", name="/train/status")


class FRRApiKeyUser(HttpUser):
    """Simulates an API-key-based integration client (higher rate, fewer endpoints)."""

    wait_time = between(0.1, 0.5)
    weight = 2  # 2x weight vs browser users

    def on_start(self):
        """Use API key auth header."""
        self.client.headers.update({"X-Api-Key": "loadtest-api-key-000"})

    @task(10)
    def latest_scores(self):
        self.client.get("/api/v1/cesi/scores", name="[api-key] /cesi/scores")

    @task(5)
    def region_detail(self):
        code = random.choice(REGIONS)
        self.client.get(f"/api/v1/cesi/{code}", name="[api-key] /cesi/[code]")

    @task(3)
    def signals(self):
        code = random.choice(REGIONS)
        self.client.get(
            f"/api/v1/signals/{code}/timeseries?source=FRED&indicator=GDP_GROWTH",
            name="[api-key] /signals/[code]/timeseries",
        )
