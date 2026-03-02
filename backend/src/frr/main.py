"""FastAPI application entry point.

Wires up routers, middleware, lifespan events, and returns the ASGI ``app`` object
that Uvicorn serves.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from frr.config import get_settings

logger = structlog.get_logger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown hook — initialise DB pool, Redis, scheduler."""
    settings = get_settings()
    logger.info(
        "Starting Future Risk Radar",
        environment=settings.environment.value,
        regions=settings.mvp_regions,
    )

    # Lazy imports to avoid circular deps
    from frr.db.session import init_db, close_db
    from frr.services.cache import init_redis, close_redis
    from frr.services.scheduler import start_scheduler, stop_scheduler

    await init_db()
    await init_redis()
    start_scheduler()

    logger.info("All services initialised — FRR is ready")
    yield

    # Shutdown
    stop_scheduler()
    await close_redis()
    await close_db()
    logger.info("Shutdown complete")


# ── App Factory ────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.api_version,
        description="Predictive global risk intelligence — structural stress detection system",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── CORS ───────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Prometheus metrics ─────────────────────────────────────────────
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # ── Routers ────────────────────────────────────────────────────────
    from frr.api.health import router as health_router
    from frr.api.regions import router as regions_router
    from frr.api.signals import router as signals_router
    from frr.api.cesi import router as cesi_router
    from frr.api.auth import router as auth_router
    from frr.api.websocket import router as ws_router
    from frr.api.training import router as training_router
    from frr.api.alerts import router as alerts_router
    from frr.api.reports import router as reports_router
    from frr.api.organizations import router as org_router
    from frr.api.audit import router as audit_router
    from frr.api.monitoring import router as monitoring_router
    from frr.api.explainability import router as explain_router
    from frr.api.nlp import router as nlp_router
    from frr.api.features import router as features_router

    prefix = f"/api/{settings.api_version}"
    app.include_router(health_router, tags=["health"])
    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(regions_router, prefix=f"{prefix}/regions", tags=["regions"])
    app.include_router(signals_router, prefix=f"{prefix}/signals", tags=["signals"])
    app.include_router(cesi_router, prefix=f"{prefix}/cesi", tags=["cesi"])
    app.include_router(training_router, prefix=prefix, tags=["training"])
    app.include_router(alerts_router, prefix=prefix, tags=["alerts"])
    app.include_router(reports_router, prefix=prefix, tags=["reports"])
    app.include_router(org_router, prefix=prefix, tags=["organizations"])
    app.include_router(audit_router, prefix=prefix, tags=["audit"])
    app.include_router(monitoring_router, prefix=prefix, tags=["monitoring"])
    app.include_router(explain_router, prefix=prefix, tags=["explainability"])
    app.include_router(nlp_router, prefix=prefix, tags=["nlp"])
    app.include_router(features_router, prefix=prefix, tags=["features"])
    app.include_router(ws_router, tags=["websocket"])

    # ── Audit logging middleware ───────────────────────────────────────
    from frr.middleware.audit import AuditLogMiddleware
    app.add_middleware(AuditLogMiddleware)

    return app


app = create_app()


# ── CLI entry (optional) ──────────────────────────────────────────────
def cli() -> None:
    """Run via ``frr`` console script."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "frr.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=settings.workers,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    cli()
