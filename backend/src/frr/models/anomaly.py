"""Anomaly detection — z-score based with rolling baseline.

Stage 1 of the FRR pipeline:
    raw signal → rolling z-score → binary anomaly flag

For each signal indicator, we compute:
    z_i(t) = (x_i(t) - mu_baseline) / sigma_baseline

where the baseline is the trailing N-year window.
An anomaly is flagged when |z| > threshold.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np
import structlog
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sqlalchemy import and_, delete, select

from frr.config import get_settings
from frr.db.models import AnomalyScore, SignalSeries

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def detect_secondary_outliers(
    values: np.ndarray,
    contamination: float = 0.08,
) -> np.ndarray:
    """Detect outliers using IsolationForest + LOF.

    Returns a boolean mask where True indicates an outlier. For stability,
    both models vote and at least one positive vote marks an outlier.
    """
    if values.ndim == 1:
        values = values.reshape(-1, 1)

    n = len(values)
    if n < 24:
        return np.zeros(n, dtype=bool)

    # Isolation Forest
    iso = IsolationForest(
        n_estimators=100,
        contamination=contamination,
        random_state=42,
    )
    iso_pred = iso.fit_predict(values)  # -1 outlier, 1 inlier

    # Local Outlier Factor
    n_neighbors = max(5, min(20, n // 4))
    lof = LocalOutlierFactor(
        n_neighbors=n_neighbors,
        contamination=contamination,
    )
    lof_pred = lof.fit_predict(values)  # -1 outlier, 1 inlier

    outlier_mask = (iso_pred == -1) | (lof_pred == -1)
    return outlier_mask.astype(bool)


class RollingWelford:
    """Numerically stable rolling mean/std with add/remove operations."""

    def __init__(self) -> None:
        self.n: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        delta2 = value - self.mean
        self.m2 += delta * delta2

    def remove(self, value: float) -> None:
        if self.n <= 1:
            self.n = 0
            self.mean = 0.0
            self.m2 = 0.0
            return

        old_mean = self.mean
        new_n = self.n - 1
        new_mean = (self.n * self.mean - value) / new_n
        self.m2 -= (value - old_mean) * (value - new_mean)
        self.mean = new_mean
        self.n = new_n

    @property
    def variance(self) -> float:
        if self.n < 2:
            return 0.0
        return max(self.m2 / (self.n - 1), 0.0)

    @property
    def std(self) -> float:
        return float(np.sqrt(self.variance))


async def compute_anomaly_scores(
    session: AsyncSession,
    region_id: str,
    layer: str | None = None,
) -> int:
    """Compute z-score anomaly scores for all signals in a region.

    If ``layer`` is provided, only computes for that signal layer.
    Returns the number of anomaly scores written.
    """
    settings = get_settings()
    baseline_years = settings.zscore_baseline_years
    threshold = settings.zscore_anomaly_threshold

    now = datetime.now(UTC)
    baseline_start = now - timedelta(days=baseline_years * 365)

    # Fetch signals
    stmt = select(SignalSeries).where(
        and_(
            SignalSeries.region_id == region_id,
            SignalSeries.ts >= baseline_start,
        )
    )
    if layer:
        stmt = stmt.where(SignalSeries.layer == layer)
    stmt = stmt.order_by(SignalSeries.ts.asc())

    result = await session.execute(stmt)
    signals = result.scalars().all()

    if not signals:
        return 0

    # Group by (source, indicator)
    grouped: dict[tuple[str, str], list[SignalSeries]] = {}
    for s in signals:
        key = (s.source, s.indicator)
        grouped.setdefault(key, []).append(s)

    # Remove old computed anomalies for this region scope to keep recomputation idempotent
    delete_stmt = delete(AnomalyScore).where(AnomalyScore.region_id == region_id)
    if layer:
        delete_stmt = delete_stmt.where(AnomalyScore.layer == layer)
    await session.execute(delete_stmt)

    count = 0
    min_baseline_points = 24
    baseline_window_days = baseline_years * 365

    for (_source, _indicator), series in grouped.items():
        rolling = RollingWelford()
        window: deque[tuple[datetime, float]] = deque()
        values = np.array([s.value for s in series], dtype=float)
        secondary_outliers = detect_secondary_outliers(values)

        for idx, s in enumerate(series):
            while window and (s.ts - window[0][0]).days > baseline_window_days:
                _, old_value = window.popleft()
                rolling.remove(old_value)

            if rolling.n >= min_baseline_points and rolling.std > 1e-10:
                z = (s.value - rolling.mean) / rolling.std
            else:
                z = 0.0

            is_anomaly = abs(z) > threshold or bool(secondary_outliers[idx])
            session.add(
                AnomalyScore(
                    signal_id=s.id,
                    region_id=s.region_id,
                    layer=s.layer,
                    ts=s.ts,
                    zscore=float(z),
                    is_anomaly=is_anomaly,
                )
            )
            count += 1

            rolling.add(s.value)
            window.append((s.ts, s.value))

    await session.commit()
    logger.info(
        "Anomaly scores computed",
        region_id=str(region_id),
        total=count,
        threshold=threshold,
    )
    return count


def rolling_zscore(values: np.ndarray, window: int = 60) -> np.ndarray:
    """Compute rolling z-score for a 1D array.

    Uses a trailing window — useful for real-time scoring.
    """
    n = len(values)
    zscores = np.zeros(n)

    for i in range(window, n):
        w = values[i - window : i]
        mu = np.mean(w)
        sigma = np.std(w)
        if sigma > 1e-10:
            zscores[i] = (values[i] - mu) / sigma

    return zscores
