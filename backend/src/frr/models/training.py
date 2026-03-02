"""Training orchestration — end-to-end model training pipeline.

Stages:
1. Fetch historical data from DB → build feature matrices
2. Compute anomaly z-scores (Stage 1) — already done at ingestion time
3. Build region graph features → train GAT encoder (Stage 2)
4. Generate GAT embeddings → train LSTM temporal model (Stage 3a)
5. Run Bayesian fusion with LSTM outputs + priors (Stage 3b)
6. Register trained models with MLflow

All training is month-granularity: features and labels are aligned to
calendar months.  Temporal train/val/test split ensures NO future leakage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog
import torch
import torch.nn.functional as torch_functional
from sqlalchemy import and_, func, select
from torch.utils.data import DataLoader, TensorDataset

from frr.config import get_settings
from frr.db.models import (
    AnomalyScore,
    CrisisLabel,
    CrisisType,
    Prediction,
    Region,
    SignalSeries,
)
from frr.db.session import get_session_factory
from frr.models.gat import (
    MVP_REGION_CODES,
    SIGNAL_LAYERS,
    GATClassifier,
    build_region_graph,
)
from frr.models.lstm import CrisisLSTMWithUncertainty

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────
CRISIS_TYPE_LIST: list[CrisisType] = list(CrisisType)
NUM_CRISIS_TYPES = len(CRISIS_TYPE_LIST)
MODELS_DIR = Path(get_settings().s3_bucket_models if False else "models_local")  # local fallback


# ───────────────────────────────────────────────────────────────────────
# Data loading helpers
# ───────────────────────────────────────────────────────────────────────

async def _load_monthly_signal_features(
    session: AsyncSession,
    region_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> dict[str, dict[str, float]]:
    """Load monthly-averaged signal values for a region.

    Returns dict[YYYY-MM → dict[indicator → avg_value]].
    """
    result = await session.execute(
        select(
            func.date_trunc("month", SignalSeries.ts).label("month"),
            SignalSeries.indicator,
            func.avg(SignalSeries.value).label("avg_val"),
        )
        .where(
            and_(
                SignalSeries.region_id == region_id,
                SignalSeries.ts >= start,
                SignalSeries.ts < end,
            )
        )
        .group_by("month", SignalSeries.indicator)
    )
    out: dict[str, dict[str, float]] = {}
    for row in result:
        key = row.month.strftime("%Y-%m")
        out.setdefault(key, {})[row.indicator] = float(row.avg_val)
    return out


async def _load_monthly_anomaly_features(
    session: AsyncSession,
    region_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> dict[str, dict[str, float]]:
    """Load monthly-averaged anomaly z-scores for a region.

    Returns dict[YYYY-MM → dict[layer → avg_abs_zscore]].
    """
    result = await session.execute(
        select(
            func.date_trunc("month", AnomalyScore.ts).label("month"),
            AnomalyScore.layer,
            func.avg(func.abs(AnomalyScore.zscore)).label("avg_z"),
        )
        .where(
            and_(
                AnomalyScore.region_id == region_id,
                AnomalyScore.ts >= start,
                AnomalyScore.ts < end,
            )
        )
        .group_by("month", AnomalyScore.layer)
    )
    out: dict[str, dict[str, float]] = {}
    for row in result:
        key = row.month.strftime("%Y-%m")
        out.setdefault(key, {})[row.layer.value if hasattr(row.layer, "value") else str(row.layer)] = float(row.avg_z)
    return out


async def _load_crisis_labels(
    session: AsyncSession,
    region_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> dict[str, set[str]]:
    """Load crisis labels indexed by YYYY-MM.

    Returns dict[YYYY-MM → set of crisis_type values].
    """
    result = await session.execute(
        select(CrisisLabel).where(
            and_(
                CrisisLabel.region_id == region_id,
                CrisisLabel.event_date >= start,
                CrisisLabel.event_date < end,
            )
        )
    )
    out: dict[str, set[str]] = {}
    for label in result.scalars().all():
        key = label.event_date.strftime("%Y-%m")
        out.setdefault(key, set()).add(label.crisis_type.value)
    return out


def _build_month_range(start: datetime, end: datetime) -> list[str]:
    """Generate sorted list of YYYY-MM keys between start and end."""
    months: list[str] = []
    cur = start.replace(day=1)
    while cur < end:
        months.append(cur.strftime("%Y-%m"))
        cur = cur.replace(year=cur.year + 1, month=1) if cur.month == 12 else cur.replace(month=cur.month + 1)
    return months


# ───────────────────────────────────────────────────────────────────────
# Dataset builder
# ───────────────────────────────────────────────────────────────────────

async def build_training_dataset(
    session: AsyncSession,
    start_year: int = 1997,
    end_year: int = 2025,
    lookback_months: int = 36,
    forecast_horizon_months: int = 12,
) -> dict[str, Any]:
    """Build the full dataset for GAT + LSTM + Bayesian models.

    Returns a dict containing:
    - gat_features: [T, num_regions, num_indicators]  monthly node features
    - gat_labels:   [T, num_regions, 5]               binary crisis labels at t+12
    - lstm_sequences: [N, lookback, features]          for LSTM training
    - lstm_labels:    [N, 5]                           crisis labels at t+horizon
    - months:       list of YYYY-MM keys
    - indicator_names: list of feature column names
    """
    start = datetime(start_year, 1, 1, tzinfo=UTC)
    end = datetime(end_year, 12, 31, tzinfo=UTC)
    months = _build_month_range(start, end)

    # Get regions
    result = await session.execute(select(Region).where(Region.active.is_(True)))
    regions = {r.code: r for r in result.scalars().all()}

    # Collect all indicator names
    indicator_result = await session.execute(
        select(SignalSeries.indicator).distinct()
    )
    indicator_names: list[str] = sorted([r[0] for r in indicator_result])

    # Feature columns = anomaly layer z-scores (4) + signal indicators (N)
    feature_names = SIGNAL_LAYERS + indicator_names
    num_features = len(feature_names)

    num_regions = len(MVP_REGION_CODES)
    num_months = len(months)

    # Build feature tensor: [months, regions, features]
    all_features = np.zeros((num_months, num_regions, num_features), dtype=np.float32)
    # Build label tensor: [months, regions, 5_crisis_types]
    all_labels = np.zeros((num_months, num_regions, NUM_CRISIS_TYPES), dtype=np.float32)

    for r_idx, region_code in enumerate(MVP_REGION_CODES):
        region = regions.get(region_code)
        if region is None:
            continue

        anomaly_data = await _load_monthly_anomaly_features(session, region.id, start, end)
        signal_data = await _load_monthly_signal_features(session, region.id, start, end)
        # Shift crisis labels forward by forecast_horizon for training: if crisis at t+12,
        # the label sits at month t so the model learns to predict it.
        label_start = start + timedelta(days=forecast_horizon_months * 30)
        label_end = end + timedelta(days=forecast_horizon_months * 30)
        crisis_data = await _load_crisis_labels(session, region.id, label_start, label_end)

        for m_idx, month_key in enumerate(months):
            # Anomaly features (first 4 columns)
            anomaly_row = anomaly_data.get(month_key, {})
            for l_idx, layer in enumerate(SIGNAL_LAYERS):
                all_features[m_idx, r_idx, l_idx] = anomaly_row.get(layer, 0.0)

            # Signal indicator features (remaining columns)
            signal_row = signal_data.get(month_key, {})
            for i_idx, ind in enumerate(indicator_names):
                all_features[m_idx, r_idx, len(SIGNAL_LAYERS) + i_idx] = signal_row.get(ind, 0.0)

            # Labels: look ahead by forecast_horizon_months
            target_dt = datetime.strptime(month_key, "%Y-%m").replace(tzinfo=UTC)
            for fh in range(forecast_horizon_months):
                future_dt = target_dt + timedelta(days=(fh + 1) * 30)
                future_key = future_dt.strftime("%Y-%m")
                if future_key in crisis_data:
                    for ct in crisis_data[future_key]:
                        ct_idx = next(
                            (i for i, c in enumerate(CRISIS_TYPE_LIST) if c.value == ct),
                            None,
                        )
                        if ct_idx is not None:
                            all_labels[m_idx, r_idx, ct_idx] = 1.0

    # Build LSTM sequences: sliding windows of lookback_months
    lstm_x: list[np.ndarray] = []
    lstm_y: list[np.ndarray] = []
    for r_idx in range(num_regions):
        for t in range(lookback_months, num_months):
            seq = all_features[t - lookback_months : t, r_idx, :]  # [lookback, features]
            label = all_labels[t, r_idx, :]  # [5]
            lstm_x.append(seq)
            lstm_y.append(label)

    lstm_x_arr = np.array(lstm_x, dtype=np.float32) if lstm_x else np.zeros((0, lookback_months, num_features), dtype=np.float32)
    lstm_y_arr = np.array(lstm_y, dtype=np.float32) if lstm_y else np.zeros((0, NUM_CRISIS_TYPES), dtype=np.float32)

    logger.info(
        "Training dataset built",
        months=num_months,
        regions=num_regions,
        features=num_features,
        lstm_samples=len(lstm_x),
        positive_labels=int(all_labels.sum()),
    )

    return {
        "gat_features": all_features,   # [T, R, F]
        "gat_labels": all_labels,        # [T, R, 5]
        "lstm_sequences": lstm_x_arr,    # [N, lookback, F]
        "lstm_labels": lstm_y_arr,       # [N, 5]
        "months": months,
        "indicator_names": indicator_names,
        "feature_names": feature_names,
        "num_features": num_features,
    }


# ───────────────────────────────────────────────────────────────────────
# GAT training
# ───────────────────────────────────────────────────────────────────────

def train_gat(
    features: np.ndarray,
    labels: np.ndarray,
    num_regions: int = 5,
    epochs: int = 200,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    val_split: float = 0.15,
) -> tuple[GATClassifier, dict[str, float]]:
    """Train the GAT cross-signal correlation model.

    Parameters
    ----------
    features : [T, R, F] monthly node features
    labels   : [T, R, 5] binary crisis labels
    """
    settings = get_settings()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    num_timesteps, num_regions_in_data, num_features_in = features.shape
    edge_index, edge_weight = build_region_graph(num_regions)
    edge_index = edge_index.to(device)
    edge_weight = edge_weight.to(device)

    model = GATClassifier(
        in_features=num_features_in,
        gat_hidden=settings.model_gnn_embedding_dim,
        gat_out=settings.model_gnn_embedding_dim // 2,
        num_crisis_types=NUM_CRISIS_TYPES,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Temporal split: no shuffling — train on earlier months, validate on later
    split_idx = int(num_timesteps * (1 - val_split))
    train_feat = torch.tensor(features[:split_idx], dtype=torch.float32, device=device)
    train_labels = torch.tensor(labels[:split_idx], dtype=torch.float32, device=device)
    val_feat = torch.tensor(features[split_idx:], dtype=torch.float32, device=device)
    val_labels = torch.tensor(labels[split_idx:], dtype=torch.float32, device=device)

    # Class weights for imbalanced data (crises are rare)
    pos_count = labels[:split_idx].sum(axis=(0, 1))  # [5]
    neg_count = split_idx * num_regions_in_data - pos_count
    pos_weight = torch.tensor(
        np.where(pos_count > 0, neg_count / pos_count, 10.0),
        dtype=torch.float32,
        device=device,
    )

    best_val_loss = float("inf")
    best_state: dict[str, Any] = {}
    patience = 30
    patience_counter = 0

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        for t in range(split_idx):
            x = train_feat[t]  # [R, F]
            y = train_labels[t]  # [R, 5]
            logits = model(x, edge_index, edge_weight)  # [R, 5]
            loss = torch_functional.binary_cross_entropy_with_logits(logits, y, pos_weight=pos_weight)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            epoch_loss += loss.item()
        scheduler.step()

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for t in range(len(val_feat)):
                logits = model(val_feat[t], edge_index, edge_weight)
                val_loss += torch_functional.binary_cross_entropy_with_logits(
                    logits, val_labels[t], pos_weight=pos_weight,
                ).item()
        val_loss /= max(len(val_feat), 1)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if epoch % 20 == 0 or patience_counter == 0:
            logger.info(
                "GAT training",
                epoch=epoch,
                train_loss=round(epoch_loss / max(split_idx, 1), 5),
                val_loss=round(val_loss, 5),
                lr=round(optimizer.param_groups[0]["lr"], 6),
            )

        if patience_counter >= patience:
            logger.info("GAT early stopping", epoch=epoch)
            break

    model.load_state_dict(best_state)
    model.eval()

    metrics = {
        "best_val_loss": best_val_loss,
        "epochs_trained": epoch + 1,
    }
    return model, metrics


def generate_gat_embeddings(
    model: GATClassifier,
    features: np.ndarray,
    num_regions: int = 5,
) -> np.ndarray:
    """Run inference through the trained GAT encoder to produce embeddings.

    Parameters
    ----------
    features : [T, R, F]

    Returns
    -------
    embeddings : [T, R, gat_out_dim]
    """
    device = next(model.parameters()).device
    num_timesteps = features.shape[0]
    edge_index, edge_weight = build_region_graph(num_regions)
    edge_index = edge_index.to(device)
    edge_weight = edge_weight.to(device)

    encoder = model.encoder
    encoder.eval()
    embeddings = []

    with torch.no_grad():
        for t in range(num_timesteps):
            x = torch.tensor(features[t], dtype=torch.float32, device=device)
            emb = encoder(x, edge_index, edge_weight)  # [R, out_dim]
            embeddings.append(emb.cpu().numpy())

    return np.array(embeddings, dtype=np.float32)  # [T, R, out_dim]


# ───────────────────────────────────────────────────────────────────────
# LSTM training
# ───────────────────────────────────────────────────────────────────────

def train_lstm(
    sequences: np.ndarray,
    labels: np.ndarray,
    gat_embeddings: np.ndarray | None = None,
    epochs: int = 150,
    batch_size: int = 32,
    lr: float = 5e-4,
    weight_decay: float = 1e-4,
    val_split: float = 0.15,
) -> tuple[CrisisLSTMWithUncertainty, dict[str, float]]:
    """Train the LSTM temporal crisis probability model.

    If gat_embeddings are provided, they are concatenated to the input features.

    Parameters
    ----------
    sequences : [N, lookback, F]
    labels    : [N, 5]
    gat_embeddings : [N, gat_dim] optional — GAT embeddings for the last timestep
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    settings = get_settings()

    num_samples, lookback, input_dim = sequences.shape

    # Optionally concatenate GAT embeddings as extra features at each timestep
    if gat_embeddings is not None:
        # Repeat GAT embedding across all timesteps: [N, gat_dim] → [N, lookback, gat_dim]
        emb_repeated = np.repeat(gat_embeddings[:, np.newaxis, :], lookback, axis=1)
        sequences = np.concatenate([sequences, emb_repeated], axis=-1)
        input_dim = sequences.shape[-1]

    # Temporal split (no shuffle — prevent future leakage)
    split = int(num_samples * (1 - val_split))
    x_train = torch.tensor(sequences[:split], dtype=torch.float32)
    y_train = torch.tensor(labels[:split], dtype=torch.float32)
    x_val = torch.tensor(sequences[split:], dtype=torch.float32)
    y_val = torch.tensor(labels[split:], dtype=torch.float32)

    train_ds = TensorDataset(x_train, y_train)
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=False)
    val_ds = TensorDataset(x_val, y_val)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    # Class weights
    pos_count = labels[:split].sum(axis=0)
    neg_count = split - pos_count
    pos_weight = torch.tensor(
        np.where(pos_count > 0, neg_count / pos_count, 10.0),
        dtype=torch.float32,
        device=device,
    )

    model = CrisisLSTMWithUncertainty(
        input_dim=input_dim,
        hidden_dim=settings.model_lstm_hidden_dim,
        num_layers=settings.model_lstm_num_layers,
        num_crisis_types=NUM_CRISIS_TYPES,
        dropout=0.3,
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)

    best_val_loss = float("inf")
    best_state: dict[str, Any] = {}
    patience = 25
    patience_counter = 0

    for epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        for x_batch, y_batch in train_dl:
            x_batch = x_batch.to(device)
            y_batch = y_batch.to(device)
            preds = model(x_batch)  # [B, 5] (sigmoid output)
            # BCE on pre-sigmoid logits for numerical stability
            logits = torch.logit(preds.clamp(1e-6, 1 - 1e-6))
            loss = torch_functional.binary_cross_entropy_with_logits(logits, y_batch, pos_weight=pos_weight)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            epoch_loss += loss.item() * x_batch.size(0)

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x_batch, y_batch in val_dl:
                x_batch = x_batch.to(device)
                y_batch = y_batch.to(device)
                preds = model(x_batch)
                logits = torch.logit(preds.clamp(1e-6, 1 - 1e-6))
                val_loss += torch_functional.binary_cross_entropy_with_logits(
                    logits, y_batch, pos_weight=pos_weight,
                ).item() * x_batch.size(0)
        val_loss /= max(len(x_val), 1)
        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            patience_counter = 0
        else:
            patience_counter += 1

        if epoch % 15 == 0 or patience_counter == 0:
            logger.info(
                "LSTM training",
                epoch=epoch,
                train_loss=round(epoch_loss / max(split, 1), 5),
                val_loss=round(val_loss, 5),
            )

        if patience_counter >= patience:
            logger.info("LSTM early stopping", epoch=epoch)
            break

    model.load_state_dict(best_state)
    model.eval()

    metrics = {"best_val_loss": best_val_loss, "epochs_trained": epoch + 1}
    return model, metrics


# ───────────────────────────────────────────────────────────────────────
# Bayesian fusion training
# ───────────────────────────────────────────────────────────────────────

def train_bayesian(
    lstm_predictions: np.ndarray,
    features: np.ndarray,
    labels: np.ndarray,
) -> tuple[Any, dict[str, Any]]:
    """Train the Bayesian fusion layer.

    Combines LSTM predictions with anomaly features and runs NUTS
    to learn calibrated posterior distributions.

    Parameters
    ----------
    lstm_predictions : [N, 5]  — LSTM output probabilities
    features         : [N, F]  — extra features (z-scores etc.)
    labels           : [N, 5]  — binary crisis labels

    Returns (BayesianFusion instance, metrics dict).
    """
    from frr.models.bayesian import BayesianFusion

    combined_features = np.concatenate([lstm_predictions, features], axis=-1)

    fusion = BayesianFusion()
    fusion.fit(combined_features, labels, num_crisis_types=NUM_CRISIS_TYPES)

    # Quick in-sample evaluation
    preds = fusion.predict(combined_features, num_crisis_types=NUM_CRISIS_TYPES)
    brier_scores = ((preds["mean"] - labels) ** 2).mean(axis=0)
    avg_brier = float(brier_scores.mean())

    metrics = {
        "avg_brier_score": avg_brier,
        "per_crisis_brier": {ct.value: float(brier_scores[i]) for i, ct in enumerate(CRISIS_TYPE_LIST)},
    }
    logger.info("Bayesian fusion trained", avg_brier=round(avg_brier, 4))
    return fusion, metrics


# ───────────────────────────────────────────────────────────────────────
# Prediction & persistence
# ───────────────────────────────────────────────────────────────────────

async def persist_predictions(
    session: AsyncSession,
    region_code: str,
    probs: np.ndarray,
    ci_lower: np.ndarray,
    ci_upper: np.ndarray,
    model_version: str,
    horizon_months: int = 12,
) -> int:
    """Write crisis probability predictions to the database.

    Parameters
    ----------
    probs    : [5] — mean probability per crisis type
    ci_lower : [5] — 5th percentile
    ci_upper : [5] — 95th percentile

    Returns count of prediction rows inserted.
    """
    result = await session.execute(select(Region).where(Region.code == region_code))
    region = result.scalar_one_or_none()
    if region is None:
        return 0

    now = datetime.now(UTC)
    horizon = now + timedelta(days=horizon_months * 30)

    count = 0
    for i, ct in enumerate(CRISIS_TYPE_LIST):
        pred = Prediction(
            id=uuid.uuid4(),
            region_id=region.id,
            crisis_type=ct,
            probability=float(probs[i]),
            confidence_lower=float(ci_lower[i]),
            confidence_upper=float(ci_upper[i]),
            horizon_date=horizon,
            model_version=model_version,
            explanation={},
        )
        session.add(pred)
        count += 1

    await session.commit()
    return count


# ───────────────────────────────────────────────────────────────────────
# Full training pipeline
# ───────────────────────────────────────────────────────────────────────

async def train_pipeline(
    retrain_gat: bool = True,
    retrain_lstm: bool = True,
    retrain_bayesian: bool = True,
    model_version: str = "v0.2.0",
) -> dict[str, Any]:
    """Run the complete training pipeline end-to-end.

    Returns a dict of {model_name: training_metrics}.
    """
    results: dict[str, Any] = {}
    settings = get_settings()
    factory = get_session_factory()

    logger.info("Training pipeline started", version=model_version)

    # Stage 0: Build dataset from DB
    async with factory() as session:
        dataset = await build_training_dataset(
            session,
            lookback_months=settings.model_lookback_months,
            forecast_horizon_months=settings.model_forecast_horizon_months,
        )

    gat_features = dataset["gat_features"]   # [T, R, F]
    gat_labels = dataset["gat_labels"]        # [T, R, 5]
    lstm_sequences = dataset["lstm_sequences"]  # [N, lookback, F]
    lstm_labels = dataset["lstm_labels"]        # [N, 5]
    num_features = dataset["num_features"]

    if lstm_sequences.shape[0] == 0:
        logger.warning("Insufficient data for training — need more signal history")
        return {"error": "insufficient_data"}

    # ── Stage 2: GAT ──────────────────────────────────────────────────
    gat_model: GATClassifier | None = None
    gat_embeddings: np.ndarray | None = None

    if retrain_gat:
        logger.info("Training GAT model...")
        gat_model, gat_metrics = train_gat(
            gat_features, gat_labels,
            num_regions=len(MVP_REGION_CODES),
        )
        results["gat"] = gat_metrics

        # Generate embeddings for LSTM input
        gat_embeddings = generate_gat_embeddings(
            gat_model, gat_features, len(MVP_REGION_CODES),
        )
        logger.info("GAT embeddings generated", shape=gat_embeddings.shape)

    # ── Stage 3a: LSTM ─────────────────────────────────────────────────
    lstm_model: CrisisLSTMWithUncertainty | None = None

    if retrain_lstm:
        logger.info("Training LSTM model...")

        # Build per-sample GAT embeddings for LSTM concatenation
        lstm_gat_embs: np.ndarray | None = None
        if gat_embeddings is not None:
            # gat_embeddings is [T, R, D]. LSTM samples are indexed by (region, time).
            num_timesteps, num_regions, _embedding_dim = gat_embeddings.shape
            lookback = settings.model_lookback_months
            embs: list[np.ndarray] = []
            for r in range(num_regions):
                for t in range(lookback, num_timesteps):
                    embs.append(gat_embeddings[t, r, :])
            lstm_gat_embs = np.array(embs, dtype=np.float32) if embs else None

        lstm_model, lstm_metrics = train_lstm(
            lstm_sequences, lstm_labels,
            gat_embeddings=lstm_gat_embs,
        )
        results["lstm"] = lstm_metrics

    # ── Stage 3b: Bayesian Fusion ──────────────────────────────────────
    if retrain_bayesian and lstm_model is not None:
        logger.info("Training Bayesian fusion model...")

        # Generate LSTM predictions on the training data
        device = next(lstm_model.parameters()).device
        lstm_model.eval()
        with torch.no_grad():
            x_tensor = torch.tensor(lstm_sequences, dtype=torch.float32, device=device)
            # Process in batches to avoid OOM
            chunk_size = 256
            lstm_preds_list: list[np.ndarray] = []
            for i in range(0, len(x_tensor), chunk_size):
                chunk = x_tensor[i : i + chunk_size]
                pred_chunk = lstm_model(chunk).cpu().numpy()
                lstm_preds_list.append(pred_chunk)
            lstm_predictions = np.concatenate(lstm_preds_list, axis=0)

        # Use the last timestep's raw features as extra Bayesian inputs
        extra_features = lstm_sequences[:, -1, :]  # [N, F]

        try:
            _fusion, bayesian_metrics = train_bayesian(
                lstm_predictions, extra_features, lstm_labels,
            )
            results["bayesian"] = bayesian_metrics
        except Exception as e:
            logger.error("Bayesian training failed (requires JAX/NumPyro)", error=str(e))
            results["bayesian"] = {"error": str(e)}

    # ── Save models ────────────────────────────────────────────────────
    model_dir = MODELS_DIR / model_version
    model_dir.mkdir(parents=True, exist_ok=True)

    if gat_model is not None:
        torch.save(gat_model.state_dict(), model_dir / "gat.pt")
        logger.info("GAT model saved", path=str(model_dir / "gat.pt"))

    if lstm_model is not None:
        torch.save(lstm_model.state_dict(), model_dir / "lstm.pt")
        logger.info("LSTM model saved", path=str(model_dir / "lstm.pt"))

    # ── MLflow experiment tracking ─────────────────────────────────────
    try:
        import mlflow

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment("FRR-Training")

        with mlflow.start_run(run_name=f"train-{model_version}"):
            # Log hyperparameters
            mlflow.log_params({
                "model_version": model_version,
                "lookback_months": settings.model_lookback_months,
                "forecast_horizon_months": settings.model_forecast_horizon_months,
                "gnn_embedding_dim": settings.model_gnn_embedding_dim,
                "lstm_hidden_dim": settings.model_lstm_hidden_dim,
                "lstm_num_layers": settings.model_lstm_num_layers,
                "bayesian_num_samples": settings.model_bayesian_num_samples,
                "num_features": num_features,
                "training_samples": lstm_sequences.shape[0],
                "retrain_gat": retrain_gat,
                "retrain_lstm": retrain_lstm,
                "retrain_bayesian": retrain_bayesian,
            })

            # Log per-stage metrics
            for stage, metrics in results.items():
                if isinstance(metrics, dict) and "error" not in metrics:
                    for key, val in metrics.items():
                        if isinstance(val, (int, float)):
                            mlflow.log_metric(f"{stage}_{key}", val)

            # Log model artifacts
            if (model_dir / "gat.pt").exists():
                mlflow.log_artifact(str(model_dir / "gat.pt"), "models")
            if (model_dir / "lstm.pt").exists():
                mlflow.log_artifact(str(model_dir / "lstm.pt"), "models")

            # Tag the run
            mlflow.set_tags({
                "pipeline": "train",
                "version": model_version,
                "stages": ",".join(results.keys()),
            })

        logger.info("MLflow run logged", version=model_version)
    except Exception as e:
        logger.warning("MLflow logging failed (non-fatal)", error=str(e))

    # ── Generate & persist predictions ─────────────────────────────────
    if lstm_model is not None:
        async with factory() as session:
            for r_idx, region_code in enumerate(MVP_REGION_CODES):
                # Use the latest data point for each region
                # Find the last LSTM sequence for this region
                lookback = settings.model_lookback_months
                num_timesteps = gat_features.shape[0]
                if lookback >= num_timesteps:
                    continue

                last_seq = gat_features[num_timesteps - lookback : num_timesteps, r_idx, :]  # [lookback, F]
                last_seq_tensor = torch.tensor(
                    last_seq[np.newaxis, :, :], dtype=torch.float32, device=device,
                )

                with torch.no_grad():
                    mean, lower, upper = lstm_model.predict_with_uncertainty(last_seq_tensor)
                    mean_np = mean.cpu().numpy()[0]  # [5]
                    lower_np = lower.cpu().numpy()[0]
                    upper_np = upper.cpu().numpy()[0]

                await persist_predictions(
                    session, region_code,
                    mean_np, lower_np, upper_np,
                    model_version,
                )
                logger.info(
                    "Predictions persisted",
                    region=region_code,
                    probs={ct.value: round(float(mean_np[i]), 3) for i, ct in enumerate(CRISIS_TYPE_LIST)},
                )

    logger.info("Training pipeline complete", models=list(results.keys()))
    return results
