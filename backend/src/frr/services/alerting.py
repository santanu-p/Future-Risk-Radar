"""Alerting service — evaluate alert rules and dispatch notifications.

Supports four delivery channels:
- **email**      — SMTP via aiosmtplib
- **slack**      — Incoming webhook POST
- **webhook**    — Arbitrary HTTPS POST with JSON payload
- **websocket**  — Publish to ``frr:alerts`` Redis channel (real-time UI)

After every CESI scoring cycle the engine calls ``evaluate_alerts()`` which:
1. Fetches all active alert rules from the DB.
2. Checks each rule against the latest metric value for its target region/crisis.
3. Respects the per-rule cooldown period before re-firing.
4. Persists an ``AlertHistory`` row and dispatches the notification.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from frr.config import get_settings
from frr.db.models import (
    AlertChannel,
    AlertHistory,
    AlertRule,
    CESIScore,
    CrisisType,
    Prediction,
    Region,
)
from frr.services.cache import publish

logger = structlog.get_logger(__name__)

# ── Operator helpers ───────────────────────────────────────────────────
_OPS: dict[str, Any] = {
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    "==": lambda v, t: abs(v - t) < 1e-9,
}


# ── Metric resolvers ──────────────────────────────────────────────────

async def _resolve_metric(
    session: AsyncSession,
    region_code: str | None,
    metric: str,
    crisis_type: CrisisType | None,
) -> list[tuple[str, float]]:
    """Return list of (region_code, value) pairs for the requested metric.

    When ``region_code`` is None, return values for ALL active regions.
    """
    results: list[tuple[str, float]] = []

    if metric == "cesi_score":
        query = (
            select(Region.code, CESIScore.score)
            .join(CESIScore, CESIScore.region_id == Region.id)
            .where(Region.active.is_(True))
            .order_by(CESIScore.scored_at.desc())
        )
        if region_code:
            query = query.where(Region.code == region_code)
        # For each region, take only the latest score
        raw = (await session.execute(query)).all()
        seen: set[str] = set()
        for code, value in raw:
            if code not in seen:
                results.append((code, float(value)))
                seen.add(code)

    elif metric == "crisis_probability" and crisis_type:
        query = (
            select(Region.code, Prediction.probability)
            .join(Prediction, Prediction.region_id == Region.id)
            .where(Region.active.is_(True), Prediction.crisis_type == crisis_type)
            .order_by(Prediction.created_at.desc())
        )
        if region_code:
            query = query.where(Region.code == region_code)
        raw = (await session.execute(query)).all()
        seen = set()
        for code, value in raw:
            if code not in seen:
                results.append((code, float(value)))
                seen.add(code)

    return results


# ── Dispatcher ─────────────────────────────────────────────────────────

async def _dispatch_email(rule: AlertRule, message: str, region: str) -> None:
    """Send an alert email via SMTP."""
    settings = get_settings()
    if not settings.smtp_host:
        logger.warning("Email alert skipped — SMTP not configured", rule=rule.name)
        return
    try:
        import aiosmtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = f"[FRR Alert] {rule.name} — {region}"
        msg["From"] = settings.smtp_from_email
        msg["To"] = rule.channel_config.get("email", settings.smtp_from_email)
        msg.set_content(message)

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password.get_secret_value() or None,
            use_tls=settings.smtp_use_tls,
        )
        logger.info("Email alert sent", rule=rule.name, to=msg["To"])
    except Exception as e:
        logger.error("Email dispatch failed", error=str(e), rule=rule.name)
        raise


async def _dispatch_slack(rule: AlertRule, message: str, region: str) -> None:
    """Post alert to a Slack incoming webhook."""
    settings = get_settings()
    webhook_url = rule.channel_config.get("webhook_url") or settings.slack_default_webhook_url
    if not webhook_url:
        logger.warning("Slack alert skipped — no webhook URL", rule=rule.name)
        return
    try:
        payload = {
            "text": f":rotating_light: *FRR Alert — {rule.name}*",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message},
                }
            ],
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
        logger.info("Slack alert sent", rule=rule.name)
    except Exception as e:
        logger.error("Slack dispatch failed", error=str(e), rule=rule.name)
        raise


async def _dispatch_webhook(rule: AlertRule, message: str, region: str, value: float) -> None:
    """POST JSON payload to an arbitrary webhook URL."""
    webhook_url = rule.channel_config.get("webhook_url")
    if not webhook_url:
        logger.warning("Webhook alert skipped — no URL configured", rule=rule.name)
        return
    try:
        payload = {
            "alert_name": rule.name,
            "region_code": region,
            "metric": rule.metric,
            "value": value,
            "threshold": rule.threshold,
            "operator": rule.operator,
            "message": message,
            "fired_at": datetime.now(timezone.utc).isoformat(),
        }
        headers = rule.channel_config.get("headers", {})
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload, headers=headers)
            resp.raise_for_status()
        logger.info("Webhook alert sent", rule=rule.name, url=webhook_url)
    except Exception as e:
        logger.error("Webhook dispatch failed", error=str(e), rule=rule.name)
        raise


async def _dispatch_websocket(rule: AlertRule, message: str, region: str, value: float) -> None:
    """Publish to Redis ``frr:alerts`` channel for live WebSocket push."""
    alert_payload = {
        "event": "alert_fired",
        "alert_name": rule.name,
        "region_code": region,
        "metric": rule.metric,
        "value": round(value, 3),
        "threshold": rule.threshold,
        "operator": rule.operator,
        "channel": rule.channel.value,
        "message": message,
        "fired_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await publish("frr:alerts", alert_payload)
    except Exception as e:
        logger.debug("WS alert publish skipped", error=str(e))


_DISPATCHERS = {
    AlertChannel.EMAIL: _dispatch_email,
    AlertChannel.SLACK: _dispatch_slack,
    AlertChannel.WEBHOOK: _dispatch_webhook,
    AlertChannel.WEBSOCKET: _dispatch_websocket,
}


# ── Main evaluation loop ──────────────────────────────────────────────

async def evaluate_alerts(session: AsyncSession) -> int:
    """Evaluate all active alert rules against the latest metric values.

    Returns the number of alerts fired.
    """
    now = datetime.now(timezone.utc)
    fired_count = 0

    # Fetch all active rules
    result = await session.execute(select(AlertRule).where(AlertRule.is_active.is_(True)))
    rules: list[AlertRule] = list(result.scalars().all())

    if not rules:
        return 0

    for rule in rules:
        try:
            # Check cooldown
            if rule.last_fired_at:
                cooldown_end = rule.last_fired_at + timedelta(minutes=rule.cooldown_minutes)
                if now < cooldown_end:
                    continue

            # Resolve crisis type if set
            crisis_type = None
            if rule.crisis_type:
                try:
                    crisis_type = CrisisType(rule.crisis_type.value if hasattr(rule.crisis_type, "value") else rule.crisis_type)
                except ValueError:
                    pass

            # Get metric values
            metric_values = await _resolve_metric(
                session, rule.region_code, rule.metric, crisis_type
            )

            # Evaluate each region against the rule
            op_fn = _OPS.get(rule.operator, _OPS[">="])
            for region_code, value in metric_values:
                if not op_fn(value, rule.threshold):
                    continue

                # Build message
                message = (
                    f"**{rule.name}** triggered for region **{region_code}**\n"
                    f"Metric `{rule.metric}` = {value:.2f} {rule.operator} threshold {rule.threshold:.2f}"
                )
                if crisis_type:
                    message += f"\nCrisis type: {crisis_type.value}"

                # Persist history
                delivery_error: str | None = None
                delivered = False
                try:
                    dispatcher = _DISPATCHERS.get(rule.channel)
                    if dispatcher:
                        if rule.channel == AlertChannel.WEBHOOK:
                            await dispatcher(rule, message, region_code, value)
                        elif rule.channel == AlertChannel.WEBSOCKET:
                            await dispatcher(rule, message, region_code, value)
                        else:
                            await dispatcher(rule, message, region_code)
                    delivered = True
                except Exception as e:
                    delivery_error = str(e)

                history = AlertHistory(
                    rule_id=rule.id,
                    region_code=region_code,
                    metric_value=value,
                    threshold=rule.threshold,
                    message=message,
                    channel=rule.channel,
                    delivered=delivered,
                    delivery_error=delivery_error,
                )
                session.add(history)

                # Always push to WebSocket channel regardless of rule channel
                if rule.channel != AlertChannel.WEBSOCKET:
                    await _dispatch_websocket(rule, message, region_code, value)

                # Update last_fired_at
                rule.last_fired_at = now
                fired_count += 1

        except Exception as e:
            logger.error("Alert rule evaluation failed", rule_id=str(rule.id), error=str(e))

    await session.commit()

    if fired_count:
        logger.info("Alerts evaluated", rules_checked=len(rules), alerts_fired=fired_count)
    return fired_count
