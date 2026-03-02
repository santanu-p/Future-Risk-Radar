"""NLP news classifier — scan GDELT/news sources for qualitative risk signals.

Pipeline:
1. Fetch recent articles from GDELT Document API (or news RSS feeds)
2. Classify each article using a fine-tuned DistilBERT or zero-shot classifier
3. Extract sentiment + risk category (sanctions, trade dispute, political crisis, etc.)
4. Convert to structured signal records in the FRR system

Categories:
- sanctions_risk — trade sanctions, export controls, financial restrictions
- trade_dispute — tariffs, trade wars, WTO disputes
- political_crisis — government collapse, coups, mass protests
- conflict_escalation — military buildup, border tensions, armed conflict
- financial_contagion — bank runs, currency crashes, sovereign debt issues
- technology_decoupling — tech bans, supply chain nationalism
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from frr.config import get_settings
from frr.db.models import Region, SignalLayer, SignalSeries

logger = structlog.get_logger(__name__)

# ── Risk categories and keywords (fallback before ML model) ────────────
RISK_CATEGORIES = {
    "sanctions_risk": [
        "sanction", "export control", "embargo", "blacklist", "entity list",
        "financial restriction", "asset freeze", "ofac", "trade ban",
    ],
    "trade_dispute": [
        "tariff", "trade war", "wto dispute", "import duty", "trade barrier",
        "anti-dumping", "countervailing", "trade deficit", "trade surplus",
    ],
    "political_crisis": [
        "coup", "government collapse", "mass protest", "revolution",
        "impeachment", "political unrest", "emergency declaration",
    ],
    "conflict_escalation": [
        "military buildup", "border tension", "armed conflict", "missile",
        "nuclear threat", "invasion", "war", "ceasefire", "casualties",
    ],
    "financial_contagion": [
        "bank run", "currency crash", "sovereign default", "debt crisis",
        "capital flight", "credit downgrade", "bailout", "liquidity crisis",
    ],
    "technology_decoupling": [
        "tech ban", "chip war", "semiconductor restriction", "data sovereignty",
        "technology transfer", "supply chain decoupling", "reshoring",
    ],
}

# Region keywords for geo-tagging
REGION_KEYWORDS: dict[str, list[str]] = {
    "EU": ["european union", "eu", "brussels", "germany", "france", "italy", "spain"],
    "MENA": ["middle east", "saudi", "iran", "iraq", "egypt", "israel", "palestine"],
    "EAST_ASIA": ["china", "beijing", "japan", "tokyo", "south korea", "seoul", "taiwan"],
    "SOUTH_ASIA": ["india", "pakistan", "bangladesh", "delhi", "mumbai"],
    "LATAM": ["brazil", "mexico", "argentina", "colombia", "latin america"],
    "NORTH_AMERICA": ["united states", "usa", "canada", "washington", "white house"],
    "SUB_SAHARAN_AFRICA": ["nigeria", "kenya", "south africa", "ethiopia", "ghana"],
    "SOUTHEAST_ASIA": ["asean", "indonesia", "thailand", "vietnam", "philippines", "singapore"],
    "CENTRAL_ASIA": ["kazakhstan", "uzbekistan", "turkmenistan", "kyrgyzstan"],
    "OCEANIA": ["australia", "new zealand", "pacific islands"],
    "EASTERN_EUROPE": ["ukraine", "russia", "belarus", "georgia", "moldova"],
    "NORDIC": ["norway", "sweden", "finland", "denmark", "iceland"],
    "GULF_STATES": ["gcc", "uae", "dubai", "qatar", "bahrain", "kuwait", "oman"],
    "CARIBBEAN": ["caribbean", "cuba", "jamaica", "haiti", "dominican republic"],
    "CENTRAL_AMERICA": ["guatemala", "honduras", "costa rica", "panama", "nicaragua"],
    "SOUTHERN_AFRICA": ["sadc", "botswana", "namibia", "zimbabwe", "zambia", "mozambique"],
}


# ── GDELT fetcher ──────────────────────────────────────────────────────

async def fetch_gdelt_articles(
    query: str = "risk OR crisis OR sanctions OR conflict",
    max_articles: int = 250,
    timespan: str = "1d",
) -> list[dict[str, Any]]:
    """Fetch articles from the GDELT Document 2.0 API.

    Returns a list of article dicts with keys: url, title, seendate, domain, language, tone.
    """
    settings = get_settings()
    base_url = settings.gdelt_api_url

    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": str(min(max_articles, settings.gdelt_max_articles_per_scan)),
        "format": "json",
        "timespan": timespan,
        "sort": "datedesc",
    }

    articles: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(base_url, params=params)
            resp.raise_for_status()
            data = resp.json()

            for art in data.get("articles", []):
                articles.append({
                    "url": art.get("url", ""),
                    "title": art.get("title", ""),
                    "seendate": art.get("seendate", ""),
                    "domain": art.get("domain", ""),
                    "language": art.get("language", ""),
                    "tone": float(art.get("tone", 0)),
                    "source_country": art.get("sourcecountry", ""),
                })

        logger.info("GDELT articles fetched", count=len(articles))
    except Exception as e:
        logger.error("GDELT fetch failed", error=str(e))

    return articles


# ── Classification ─────────────────────────────────────────────────────

def _keyword_classify(text: str) -> tuple[str | None, float]:
    """Fast keyword-based classification (fallback when ML model unavailable)."""
    text_lower = text.lower()
    best_category = None
    best_score = 0.0

    for category, keywords in RISK_CATEGORIES.items():
        matches = sum(1 for kw in keywords if kw in text_lower)
        if matches > best_score:
            best_score = matches
            best_category = category

    if best_category and best_score >= 1:
        confidence = min(0.5 + best_score * 0.1, 0.9)
        return best_category, confidence

    return None, 0.0


def _detect_regions(text: str) -> list[str]:
    """Detect which regions an article relates to based on keyword matching."""
    text_lower = text.lower()
    matched: list[str] = []

    for region_code, keywords in REGION_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            matched.append(region_code)

    return matched if matched else ["GLOBAL"]


async def classify_article(text: str) -> tuple[str | None, float]:
    """Classify an article's risk category.

    Tries ML model first, falls back to keyword matching.
    """
    settings = get_settings()

    # Try transformer-based classification
    try:
        from transformers import pipeline

        classifier = pipeline(
            "zero-shot-classification",
            model=settings.nlp_classifier_model,
        )
        candidate_labels = list(RISK_CATEGORIES.keys())
        result = classifier(text[:512], candidate_labels, multi_label=False)

        top_label = result["labels"][0]
        top_score = result["scores"][0]

        if top_score >= settings.nlp_confidence_threshold:
            return top_label, top_score
    except Exception as e:
        logger.debug("ML classifier unavailable, using keywords", error=str(e))

    # Fallback to keyword matching
    return _keyword_classify(text)


def extract_sentiment(tone_value: float) -> float:
    """Convert GDELT tone value to a -1 to +1 sentiment score."""
    # GDELT tone ranges roughly from -20 to +20
    return max(-1.0, min(1.0, tone_value / 10.0))


# ── Pipeline: scan → classify → ingest ────────────────────────────────

async def scan_and_ingest_news(session: AsyncSession) -> dict[str, int]:
    """Full NLP pipeline: fetch GDELT → classify → write signal records.

    Returns summary stats.
    """
    settings = get_settings()

    # Fetch articles
    articles = await fetch_gdelt_articles(
        max_articles=settings.gdelt_max_articles_per_scan,
    )

    if not articles:
        return {"articles_scanned": 0, "signals_extracted": 0, "region_breakdown": {}}

    # Load region lookup
    region_result = await session.execute(select(Region).where(Region.active.is_(True)))
    regions_map = {r.code: r for r in region_result.scalars().all()}

    signals_count = 0
    region_counts: dict[str, int] = {}

    for article in articles:
        title = article.get("title", "")
        if not title:
            continue

        # Classify
        risk_category, confidence = await classify_article(title)
        if risk_category is None or confidence < settings.nlp_confidence_threshold:
            continue

        # Detect regions
        affected_regions = _detect_regions(title)
        sentiment = extract_sentiment(article.get("tone", 0))

        # Parse date
        try:
            seen_date = article.get("seendate", "")
            if seen_date:
                ts = datetime.strptime(seen_date[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            else:
                ts = datetime.now(timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)

        # Create signal records
        for region_code in affected_regions:
            region = regions_map.get(region_code)
            if region is None:
                continue

            signal = SignalSeries(
                region_id=region.id,
                layer=SignalLayer.ENERGY_CONFLICT,  # NLP signals map to energy_conflict layer
                source="GDELT_NLP",
                indicator=f"nlp_{risk_category}",
                ts=ts,
                value=sentiment * confidence * 100,  # Scaled -100 to +100
                metadata={
                    "title": title[:256],
                    "url": article.get("url", "")[:512],
                    "risk_category": risk_category,
                    "confidence": round(confidence, 3),
                    "sentiment": round(sentiment, 3),
                    "domain": article.get("domain", ""),
                },
            )
            session.add(signal)
            signals_count += 1
            region_counts[region_code] = region_counts.get(region_code, 0) + 1

    if signals_count > 0:
        await session.commit()

    logger.info(
        "NLP scan complete",
        articles_scanned=len(articles),
        signals_extracted=signals_count,
        regions=region_counts,
    )

    return {
        "articles_scanned": len(articles),
        "signals_extracted": signals_count,
        "region_breakdown": region_counts,
    }
