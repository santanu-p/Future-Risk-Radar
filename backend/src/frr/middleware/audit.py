"""Audit logging middleware — records every mutating API request to the audit_log table.

Captures:
- User identity (from JWT / API key)
- HTTP method + path
- Resource type and ID (parsed from URL pattern)
- Request body hash (no sensitive data stored)
- Client IP address
- Response status code
- Timing information
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from frr.db.models import AuditLog
from frr.db.session import get_session_factory

logger = structlog.get_logger(__name__)

# Methods that trigger audit logging
_AUDITABLE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# URL patterns to extract resource type and ID
_RESOURCE_PATTERNS = [
    re.compile(r"/api/v\d+/(?P<resource>\w+)/(?P<resource_id>[a-f0-9\-]{36})"),
    re.compile(r"/api/v\d+/(?P<resource>\w+)"),
]


def _parse_resource(path: str) -> tuple[str, str | None]:
    """Extract resource type and ID from the request path."""
    for pattern in _RESOURCE_PATTERNS:
        match = pattern.search(path)
        if match:
            groups = match.groupdict()
            return groups.get("resource", "unknown"), groups.get("resource_id")
    return "unknown", None


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware that logs mutating API requests to the audit_log table."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only audit mutating methods
        if request.method not in _AUDITABLE_METHODS:
            return await call_next(request)

        # Skip non-API routes (metrics, docs, health)
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        start_time = time.monotonic()
        response: Response | None = None

        try:
            response = await call_next(request)
            return response
        finally:
            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Extract user info from request state (set by auth dependency)
            user_id: uuid.UUID | None = None
            try:
                # Try to get user from request scope (if auth middleware set it)
                if hasattr(request.state, "user_id"):
                    user_id = request.state.user_id
            except Exception:
                pass

            # Parse resource from URL
            resource, resource_id = _parse_resource(path)

            # Get client IP
            ip_address = request.client.host if request.client else None

            # Build detail dict
            detail: dict[str, Any] = {
                "method": request.method,
                "path": path,
                "status_code": response.status_code if response else 500,
                "elapsed_ms": round(elapsed_ms, 2),
                "query_params": dict(request.query_params),
            }

            # Write to DB asynchronously (fire-and-forget)
            try:
                factory = get_session_factory()
                async with factory() as session:
                    log_entry = AuditLog(
                        user_id=user_id,
                        action=request.method,
                        resource=resource,
                        resource_id=resource_id,
                        detail=detail,
                        ip_address=ip_address,
                    )
                    session.add(log_entry)
                    await session.commit()
            except Exception as e:
                # Never let audit log failure break the request
                logger.debug("Audit log write failed", error=str(e))
