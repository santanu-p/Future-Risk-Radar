"""Shared exception hierarchy for the FRR domain."""

from __future__ import annotations


class FRRError(Exception):
    """Base exception for all FRR domain errors."""

    def __init__(self, message: str = "", *, code: str = "FRR_ERROR") -> None:
        self.code = code
        super().__init__(message)


# ── Ingestion ──────────────────────────────────────────────────────────
class IngestionError(FRRError):
    """Failed to ingest data from an external source."""

    def __init__(self, source: str, detail: str = "") -> None:
        super().__init__(f"[{source}] {detail}", code="INGESTION_ERROR")
        self.source = source


class RateLimitError(IngestionError):
    """Upstream API returned 429 — back off."""

    def __init__(self, source: str, retry_after: int | None = None) -> None:
        super().__init__(source, f"Rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


# ── Database ───────────────────────────────────────────────────────────
class DatabaseError(FRRError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(detail, code="DB_ERROR")


class NotFoundError(FRRError):
    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(f"{entity} '{identifier}' not found", code="NOT_FOUND")
        self.entity = entity
        self.identifier = identifier


# ── Model / Scoring ───────────────────────────────────────────────────
class ModelError(FRRError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(detail, code="MODEL_ERROR")


class ScoringError(FRRError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(detail, code="SCORING_ERROR")


# ── Auth ───────────────────────────────────────────────────────────────
class AuthError(FRRError):
    def __init__(self, detail: str = "Authentication failed") -> None:
        super().__init__(detail, code="AUTH_ERROR")
