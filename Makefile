.PHONY: dev dev-backend dev-frontend up down migrate seed test lint fmt

# ── Development ────────────────────────────────────────────────────────
dev: up dev-backend dev-frontend

dev-backend:
	cd backend && uv run uvicorn frr.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# ── Docker Compose ─────────────────────────────────────────────────────
up:
	docker compose up -d timescaledb redis minio

down:
	docker compose down

up-all:
	docker compose up -d

# ── Database ───────────────────────────────────────────────────────────
migrate:
	cd backend && uv run alembic upgrade head

migrate-create:
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"

seed:
	cd backend && uv run python -m frr.db.seed

# ── Testing ────────────────────────────────────────────────────────────
test:
	cd backend && uv run pytest -v

test-cov:
	cd backend && uv run pytest --cov=frr --cov-report=html

test-frontend:
	cd frontend && npm test

# ── Quality ────────────────────────────────────────────────────────────
lint:
	cd backend && uv run ruff check src/ tests/
	cd frontend && npm run lint

fmt:
	cd backend && uv run ruff format src/ tests/
	cd frontend && npm run format

typecheck:
	cd backend && uv run mypy src/frr/
	cd frontend && npm run typecheck

# ── ML Pipeline ────────────────────────────────────────────────────────
ingest:
	cd backend && uv run python -m frr.ingestion.runner

train:
	cd backend && uv run python -m frr.models.train

backtest:
	cd backend && uv run python -m frr.models.backtest

# ── Production ─────────────────────────────────────────────────────────
build-backend:
	docker build -t frr-backend:latest -f infra/docker/backend.Dockerfile .

build-frontend:
	cd frontend && npm run build
	docker build -t frr-frontend:latest -f infra/docker/frontend.Dockerfile .
