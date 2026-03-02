# ── Backend Dockerfile (multi-stage) ──────────────────────────────────

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files first (cache layer)
COPY pyproject.toml ./

# Install dependencies
RUN uv sync --no-dev --frozen 2>/dev/null || uv pip install --system -r <(uv pip compile pyproject.toml)

# Copy source
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

# System deps for asyncpg and torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

# Non-root user
RUN useradd --create-home --shell /bin/bash frr
USER frr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "frr.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
