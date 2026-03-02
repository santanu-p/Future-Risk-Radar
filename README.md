# 🌍 Future Risk Radar

**Predictive Global Risk Intelligence Platform**

A structural stress detection system that detects weak global signals and estimates the probability of economic instability in a given region within 12 months. This is NOT a news tracker — it is a forward-looking predictive intelligence system.

## Core Output

> *"Probability of economic instability in X region within 12 months."*

Expressed as a **Composite Economic Stress Index (CESI)** score (0–100) with decomposed categorical crisis probabilities: recession, currency crisis, sovereign default, banking crisis, political unrest.

## Signal Layers

| Layer | Signals |
|---|---|
| **Research Funding** | Grant flows, defense R&D spending, academic publication velocity in dual-use fields |
| **Patent Trends** | Filing velocity by jurisdiction, cross-border citation shifts, IP concentration in strategic domains |
| **Supply Chain Stress** | Container shipping rate anomalies, port congestion, critical mineral stockpiles, trade route deviations |
| **Energy & Conflict** | Wholesale power volatility, gas storage anomalies, military procurement, armed conflict clustering, refugee flows |

## Architecture

```
Data Ingestion → Normalization → Anomaly Detection → GNN Correlation → Bayesian+LSTM Fusion → Spatial Propagation → CESI Score
```

## Quick Start

```bash
# Clone
git clone <repo-url> && cd sp-monitor

# Start all services (TimescaleDB, Redis, MinIO, backend, frontend)
docker compose up -d

# Or run backend/frontend individually:
cd backend && uv sync && uv run uvicorn frr.main:app --reload
cd frontend && npm install && npm run dev
```

## Project Structure

```
sp-monitor/
├── backend/             # Python FastAPI + ML pipeline
│   └── src/frr/
│       ├── api/         # REST + WebSocket endpoints
│       ├── db/          # TimescaleDB + PostgreSQL models
│       ├── ingestion/   # Data source clients (25+ APIs)
│       ├── models/      # GAT, LSTM, Bayesian fusion
│       ├── scoring/     # CESI computation engine
│       └── services/    # Business logic layer
├── frontend/            # TypeScript + Vite + deck.gl
│   └── src/
│       ├── components/  # Globe, panels, charts
│       ├── services/    # API clients, WebSocket
│       └── stores/      # State management
├── infra/               # Docker Compose, K8s manifests
├── data/                # Schemas, migrations, seeds
└── models/              # Training scripts, configs
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, Pydantic v2 |
| ML | PyTorch 2.x, PyTorch Geometric, NumPyro (JAX) |
| Time-Series | TimescaleDB (PostgreSQL extension) |
| Cache | Redis 7 |
| Storage | MinIO (S3-compatible) |
| Frontend | TypeScript, Vite 6, deck.gl, MapLibre GL, D3.js |
| Infra | Docker Compose (dev), Kubernetes (prod) |

## License

AGPL-3.0
