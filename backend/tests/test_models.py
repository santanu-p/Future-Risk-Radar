"""Tests for DB model enumerations and basic model classes."""

from __future__ import annotations

from frr.db.models import (
    AlertChannel,
    CrisisType,
    DriftType,
    ReportFormat,
    SeverityBand,
    SignalLayer,
    UserRole,
)


class TestSignalLayerEnum:
    def test_values(self):
        assert SignalLayer.RESEARCH_FUNDING.value == "research_funding"
        assert SignalLayer.PATENT_ACTIVITY.value == "patent_activity"
        assert SignalLayer.SUPPLY_CHAIN.value == "supply_chain"
        assert SignalLayer.ENERGY_CONFLICT.value == "energy_conflict"

    def test_count(self):
        assert len(SignalLayer) == 4


class TestCrisisTypeEnum:
    def test_values(self):
        assert CrisisType.RECESSION.value == "recession"
        assert CrisisType.CURRENCY_CRISIS.value == "currency_crisis"
        assert CrisisType.SOVEREIGN_DEFAULT.value == "sovereign_default"
        assert CrisisType.BANKING_CRISIS.value == "banking_crisis"
        assert CrisisType.POLITICAL_UNREST.value == "political_unrest"

    def test_count(self):
        assert len(CrisisType) == 5


class TestSeverityBandEnum:
    def test_values(self):
        assert SeverityBand.STABLE.value == "stable"
        assert SeverityBand.ELEVATED.value == "elevated"
        assert SeverityBand.CONCERNING.value == "concerning"
        assert SeverityBand.HIGH_RISK.value == "high_risk"
        assert SeverityBand.CRITICAL.value == "critical"

    def test_count(self):
        assert len(SeverityBand) == 5


class TestUserRoleEnum:
    def test_values(self):
        assert UserRole.VIEWER.value == "viewer"
        assert UserRole.ANALYST.value == "analyst"
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.SUPER_ADMIN.value == "super_admin"


class TestAlertChannelEnum:
    def test_values(self):
        assert AlertChannel.EMAIL.value == "email"
        assert AlertChannel.SLACK.value == "slack"
        assert AlertChannel.WEBHOOK.value == "webhook"
        assert AlertChannel.WEBSOCKET.value == "websocket"


class TestReportFormatEnum:
    def test_values(self):
        assert ReportFormat.PDF.value == "pdf"
        assert ReportFormat.HTML.value == "html"
