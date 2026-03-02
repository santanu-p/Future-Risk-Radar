"""Back-testing framework — validate CESI against historical crises.

For each historical crisis label, checks whether FRR would have issued
a warning (elevated CESI or high crisis probability) in the 3–12 month
window before the event.

Metrics:
- True Positive Rate (recall): % of real crises detected
- False Alarm Rate: % of high-CESI periods that weren't followed by a crisis
- Lead Time: average months of warning before event
- Brier Score: probability calibration per crisis type
- Brier Skill Score: improvement over a naive baseline (trailing 5-year frequency)
- ROC AUC: per crisis type discrimination capability

Target known crises (Phase 2 validation):
- 2020 COVID economic shock (global)
- 2022 European energy crisis (EU)
- 2022 Sri Lanka sovereign default (SOUTH_ASIA)
- 2023 US regional banking stress (EU proxy)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from frr.db.models import CESIScore, CrisisLabel, CrisisType, Prediction, Region
from frr.db.session import get_session_factory
from frr.models.propagation import propagate_scores

logger = structlog.get_logger(__name__)

CRISIS_TYPE_LIST = list(CrisisType)


# ── Data classes ───────────────────────────────────────────────────────

@dataclass
class CrisisDetection:
    """Detection result for a single historical crisis."""
    crisis_date: datetime
    crisis_type: str
    region: str
    detected: bool = False
    first_warning: datetime | None = None
    lead_months: float | None = None
    peak_score: float = 0.0
    peak_probability: float = 0.0


@dataclass
class BrierResult:
    """Brier score and skill score per crisis type."""
    crisis_type: str
    brier_score: float = 0.0
    naive_baseline: float = 0.0
    brier_skill_score: float = 0.0
    n_samples: int = 0


@dataclass
class ROCResult:
    """ROC metrics per crisis type."""
    crisis_type: str
    auc: float = 0.0
    optimal_threshold: float = 0.5
    tpr_at_optimal: float = 0.0
    fpr_at_optimal: float = 0.0


@dataclass
class BacktestResult:
    """Comprehensive result of a back-test run."""
    # Detection metrics
    total_crises: int = 0
    detected: int = 0
    false_alarms: int = 0
    avg_lead_time_months: float = 0.0
    recall: float = 0.0
    precision: float = 0.0
    f1: float = 0.0

    # Probability calibration
    brier_scores: list[BrierResult] = field(default_factory=list)
    avg_brier_score: float = 0.0
    avg_brier_skill_score: float = 0.0

    # ROC
    roc_results: list[ROCResult] = field(default_factory=list)
    avg_auc: float = 0.0

    # Calibration
    calibration_curves: list[dict[str, Any]] = field(default_factory=list)

    # Detailed
    detections: list[CrisisDetection] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)

    # Known crisis validations
    known_crisis_validations: list[dict[str, Any]] = field(default_factory=list)


# ── Core backtesting ──────────────────────────────────────────────────

def run_backtest(
    cesi_history: list[tuple[datetime, float]],
    crisis_dates: list[datetime],
    warning_threshold: float = 40.0,
    detection_window_months: int = 12,
) -> BacktestResult:
    """Run a back-test against historical data (CESI-based).

    Parameters
    ----------
    cesi_history : list of (datetime, score)
        Historical CESI score series for a region.
    crisis_dates : list of datetime
        Ground-truth crisis event dates.
    warning_threshold : float
        CESI score above which we consider a warning issued.
    detection_window_months : int
        Look-back window before a crisis — if CESI exceeded threshold
        in this window, it's a hit.
    """
    result = BacktestResult(total_crises=len(crisis_dates))

    if not cesi_history or not crisis_dates:
        return result

    # Sort
    cesi_history.sort(key=lambda x: x[0])
    lead_times: list[float] = []

    for crisis_date in crisis_dates:
        window_start = crisis_date - timedelta(days=detection_window_months * 30)

        # Find first warning in the detection window
        first_warning: datetime | None = None
        peak_score = 0.0
        for ts, score in cesi_history:
            if window_start <= ts < crisis_date:
                peak_score = max(peak_score, score)
                if score >= warning_threshold and first_warning is None:
                    first_warning = ts

        detected = first_warning is not None
        lead_months = None
        if detected:
            result.detected += 1
            lead_months = (crisis_date - first_warning).days / 30.0
            lead_times.append(lead_months)

        detection = CrisisDetection(
            crisis_date=crisis_date,
            crisis_type="unknown",
            region="unknown",
            detected=detected,
            first_warning=first_warning,
            lead_months=lead_months,
            peak_score=peak_score,
        )
        result.detections.append(detection)

        result.details.append({
            "crisis_date": crisis_date.isoformat(),
            "detected": detected,
            "first_warning": first_warning.isoformat() if first_warning else None,
            "lead_months": lead_months,
            "peak_score": peak_score,
        })

    # False alarms: high-CESI periods not followed by a crisis within the window
    warning_periods = [ts for ts, score in cesi_history if score >= warning_threshold]
    for ts in warning_periods:
        window_end = ts + timedelta(days=detection_window_months * 30)
        is_true_positive = any(ts <= cd <= window_end for cd in crisis_dates)
        if not is_true_positive:
            result.false_alarms += 1

    # Metrics
    result.avg_lead_time_months = float(np.mean(lead_times)) if lead_times else 0.0
    result.recall = result.detected / result.total_crises if result.total_crises > 0 else 0.0

    total_warnings = result.detected + result.false_alarms
    result.precision = result.detected / total_warnings if total_warnings > 0 else 0.0

    if result.precision + result.recall > 0:
        result.f1 = 2 * result.precision * result.recall / (result.precision + result.recall)

    logger.info(
        "Back-test complete",
        recall=round(result.recall, 3),
        precision=round(result.precision, 3),
        f1=round(result.f1, 3),
        avg_lead_months=round(result.avg_lead_time_months, 1),
    )
    return result


# ── Probability-based backtesting ─────────────────────────────────────

def compute_brier_scores(
    predictions: np.ndarray,
    labels: np.ndarray,
    baseline_rate: np.ndarray | None = None,
) -> list[BrierResult]:
    """Compute Brier score and Brier Skill Score per crisis type.

    Parameters
    ----------
    predictions : [N, 5] — predicted probabilities per crisis type
    labels      : [N, 5] — binary ground truth
    baseline_rate : [5] — naive baseline (trailing 5-year crisis frequency)

    Returns list of BrierResult per crisis type.
    """
    N = predictions.shape[0]
    results: list[BrierResult] = []

    for i, ct in enumerate(CRISIS_TYPE_LIST):
        preds = predictions[:, i]
        actual = labels[:, i]

        brier = float(np.mean((preds - actual) ** 2))

        # Naive baseline: predict the average frequency
        if baseline_rate is not None:
            naive = float(np.mean((baseline_rate[i] - actual) ** 2))
        else:
            naive = float(np.mean((actual.mean() - actual) ** 2))

        bss = 1.0 - (brier / naive) if naive > 0 else 0.0

        results.append(BrierResult(
            crisis_type=ct.value,
            brier_score=round(brier, 5),
            naive_baseline=round(naive, 5),
            brier_skill_score=round(bss, 5),
            n_samples=N,
        ))

    return results


def compute_roc_metrics(
    predictions: np.ndarray,
    labels: np.ndarray,
    n_thresholds: int = 100,
) -> list[ROCResult]:
    """Compute ROC AUC and optimal threshold per crisis type.

    Uses a simple threshold sweep (no sklearn dependency).
    """
    results: list[ROCResult] = []
    thresholds = np.linspace(0, 1, n_thresholds)

    for i, ct in enumerate(CRISIS_TYPE_LIST):
        preds = predictions[:, i]
        actual = labels[:, i].astype(bool)

        if actual.sum() == 0 or (~actual).sum() == 0:
            results.append(ROCResult(crisis_type=ct.value, auc=0.5))
            continue

        tprs: list[float] = []
        fprs: list[float] = []

        for thresh in thresholds:
            predicted_pos = preds >= thresh
            tp = float(np.sum(predicted_pos & actual))
            fp = float(np.sum(predicted_pos & ~actual))
            fn = float(np.sum(~predicted_pos & actual))
            tn = float(np.sum(~predicted_pos & ~actual))

            tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
            tprs.append(tpr)
            fprs.append(fpr)

        # AUC via trapezoidal rule
        sorted_pairs = sorted(zip(fprs, tprs))
        fprs_sorted = [p[0] for p in sorted_pairs]
        tprs_sorted = [p[1] for p in sorted_pairs]
        auc = float(np.trapz(tprs_sorted, fprs_sorted))

        # Optimal threshold: maximize Youden's J statistic = TPR - FPR
        j_scores = [tpr - fpr for tpr, fpr in zip(tprs, fprs)]
        best_idx = int(np.argmax(j_scores))

        results.append(ROCResult(
            crisis_type=ct.value,
            auc=round(abs(auc), 4),
            optimal_threshold=round(float(thresholds[best_idx]), 3),
            tpr_at_optimal=round(tprs[best_idx], 3),
            fpr_at_optimal=round(fprs[best_idx], 3),
        ))

    return results


def compute_calibration_curves(
    predictions: np.ndarray,
    labels: np.ndarray,
    n_bins: int = 10,
) -> list[dict[str, Any]]:
    """Compute reliability diagram data per crisis type.

    Returns per-type binned points with:
    - mean predicted probability in the bin
    - observed event frequency in the bin
    - sample count in the bin
    """
    curves: list[dict[str, Any]] = []
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)

    for i, ct in enumerate(CRISIS_TYPE_LIST):
        preds = predictions[:, i]
        actual = labels[:, i]
        points: list[dict[str, Any]] = []

        for b in range(n_bins):
            lo = float(bin_edges[b])
            hi = float(bin_edges[b + 1])
            if b == n_bins - 1:
                mask = (preds >= lo) & (preds <= hi)
            else:
                mask = (preds >= lo) & (preds < hi)

            count = int(mask.sum())
            if count == 0:
                continue

            avg_pred = float(np.mean(preds[mask]))
            observed_freq = float(np.mean(actual[mask]))

            points.append(
                {
                    "bin_lower": lo,
                    "bin_upper": hi,
                    "avg_pred": round(avg_pred, 5),
                    "observed_freq": round(observed_freq, 5),
                    "n_samples": count,
                }
            )

        curves.append({"crisis_type": ct.value, "points": points})

    return curves


# ── Known crisis validation ───────────────────────────────────────────

KNOWN_CRISES = [
    {
        "name": "2020 COVID economic shock",
        "date": "2020-03-01",
        "regions": ["EU", "MENA", "EAST_ASIA", "SOUTH_ASIA", "LATAM"],
        "expected_types": ["recession"],
        "min_lead_months": 3,
    },
    {
        "name": "2022 European energy crisis",
        "date": "2022-08-01",
        "regions": ["EU"],
        "expected_types": ["recession"],
        "min_lead_months": 3,
    },
    {
        "name": "2022 Sri Lanka sovereign default",
        "date": "2022-04-12",
        "regions": ["SOUTH_ASIA"],
        "expected_types": ["sovereign_default", "currency_crisis"],
        "min_lead_months": 3,
    },
    {
        "name": "2023 US regional banking stress",
        "date": "2023-03-10",
        "regions": ["EU"],
        "expected_types": ["banking_crisis"],
        "min_lead_months": 3,
    },
]


async def validate_known_crises(
    session: AsyncSession,
    cesi_threshold: float = 60.0,
) -> list[dict[str, Any]]:
    """Check if the model would have flagged known crises with CESI > threshold
    at least N months before onset.

    Returns a list of validation results.
    """
    validations: list[dict[str, Any]] = []

    for crisis in KNOWN_CRISES:
        crisis_date = datetime.fromisoformat(crisis["date"]).replace(tzinfo=timezone.utc)
        window_start = crisis_date - timedelta(days=crisis["min_lead_months"] * 30)

        for region_code in crisis["regions"]:
            region_result = await session.execute(
                select(Region).where(Region.code == region_code)
            )
            region = region_result.scalar_one_or_none()
            if region is None:
                continue

            # Check CESI scores in the warning window
            cesi_result = await session.execute(
                select(CESIScore)
                .where(
                    and_(
                        CESIScore.region_id == region.id,
                        CESIScore.scored_at >= window_start,
                        CESIScore.scored_at < crisis_date,
                    )
                )
                .order_by(CESIScore.scored_at.asc())
            )
            cesi_scores = cesi_result.scalars().all()

            first_warning = None
            peak_score = 0.0
            for score in cesi_scores:
                peak_score = max(peak_score, score.score)
                if score.score >= cesi_threshold and first_warning is None:
                    first_warning = score.scored_at

            detected = first_warning is not None
            lead_months = (crisis_date - first_warning).days / 30.0 if first_warning else 0.0

            # Check predictions for expected crisis types
            pred_probs: dict[str, float] = {}
            for ct_str in crisis["expected_types"]:
                ct = CrisisType(ct_str)
                pred_result = await session.execute(
                    select(Prediction)
                    .where(
                        and_(
                            Prediction.region_id == region.id,
                            Prediction.crisis_type == ct,
                            Prediction.created_at >= window_start,
                            Prediction.created_at < crisis_date,
                        )
                    )
                    .order_by(Prediction.probability.desc())
                    .limit(1)
                )
                pred = pred_result.scalar_one_or_none()
                if pred:
                    pred_probs[ct_str] = pred.probability

            validations.append({
                "crisis": crisis["name"],
                "region": region_code,
                "crisis_date": crisis_date.isoformat(),
                "detected": detected,
                "lead_months": round(lead_months, 1),
                "peak_cesi": round(peak_score, 1),
                "prediction_probs": pred_probs,
                "met_target": detected and lead_months >= crisis["min_lead_months"],
            })

    logger.info(
        "Known crisis validation complete",
        total=len(validations),
        detected=sum(1 for v in validations if v["detected"]),
        met_target=sum(1 for v in validations if v["met_target"]),
    )
    return validations


# ── Full backtest orchestration ───────────────────────────────────────

async def run_full_backtest(
    start_year: int = 2015,
    end_year: int = 2024,
    cesi_threshold: float = 40.0,
    detection_window_months: int = 12,
) -> BacktestResult:
    """Run the full backtesting pipeline:
    1. Load historical CESI scores and crisis labels
    2. Compute detection metrics (recall, precision, F1, lead time)
    3. Compute Brier scores and skill scores
    4. Compute ROC AUC per crisis type
    5. Validate against known crises

    Returns a comprehensive BacktestResult.
    """
    factory = get_session_factory()
    start_dt = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(end_year, 12, 31, tzinfo=timezone.utc)

    all_cesi_history: list[tuple[datetime, float]] = []
    all_crisis_dates: list[datetime] = []
    all_predictions: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []

    async with factory() as session:
        regions_result = await session.execute(
            select(Region).where(Region.active.is_(True))
        )
        regions = regions_result.scalars().all()

        for region in regions:
            # Load CESI history
            cesi_result = await session.execute(
                select(CESIScore)
                .where(
                    and_(
                        CESIScore.region_id == region.id,
                        CESIScore.scored_at >= start_dt,
                        CESIScore.scored_at <= end_dt,
                    )
                )
                .order_by(CESIScore.scored_at.asc())
            )
            for score in cesi_result.scalars().all():
                all_cesi_history.append((score.scored_at, score.score))

            # Load crisis labels
            labels_result = await session.execute(
                select(CrisisLabel)
                .where(
                    and_(
                        CrisisLabel.region_id == region.id,
                        CrisisLabel.event_date >= start_dt,
                        CrisisLabel.event_date <= end_dt,
                    )
                )
            )
            for label in labels_result.scalars().all():
                all_crisis_dates.append(label.event_date)

            # Load predictions for Brier score computation
            pred_result = await session.execute(
                select(Prediction)
                .where(
                    and_(
                        Prediction.region_id == region.id,
                        Prediction.created_at >= start_dt,
                        Prediction.created_at <= end_dt,
                    )
                )
                .order_by(Prediction.created_at.asc())
            )
            preds = pred_result.scalars().all()
            for pred in preds:
                pred_vec = np.zeros(len(CRISIS_TYPE_LIST))
                label_vec = np.zeros(len(CRISIS_TYPE_LIST))
                ct_idx = CRISIS_TYPE_LIST.index(pred.crisis_type)
                pred_vec[ct_idx] = pred.probability
                # Check if there's a matching crisis label
                has_crisis = any(
                    label.event_date <= pred.horizon_date
                    for label in (await session.execute(
                        select(CrisisLabel).where(
                            and_(
                                CrisisLabel.region_id == region.id,
                                CrisisLabel.crisis_type == pred.crisis_type,
                                CrisisLabel.event_date >= pred.created_at,
                                CrisisLabel.event_date <= pred.horizon_date,
                            )
                        )
                    )).scalars().all()
                )
                if has_crisis:
                    label_vec[ct_idx] = 1.0
                all_predictions.append(pred_vec)
                all_labels.append(label_vec)

        # Run CESI-based backtest
        result = run_backtest(
            all_cesi_history,
            all_crisis_dates,
            warning_threshold=cesi_threshold,
            detection_window_months=detection_window_months,
        )

        # Compute probability calibration metrics
        if all_predictions:
            preds_arr = np.array(all_predictions)
            labels_arr = np.array(all_labels)

            result.brier_scores = compute_brier_scores(preds_arr, labels_arr)
            result.avg_brier_score = float(np.mean([b.brier_score for b in result.brier_scores]))
            result.avg_brier_skill_score = float(np.mean([b.brier_skill_score for b in result.brier_scores]))

            result.roc_results = compute_roc_metrics(preds_arr, labels_arr)
            result.avg_auc = float(np.mean([r.auc for r in result.roc_results]))
            result.calibration_curves = compute_calibration_curves(preds_arr, labels_arr)

        # Validate known crises
        result.known_crisis_validations = await validate_known_crises(session, cesi_threshold=60.0)

    logger.info(
        "Full backtest complete",
        recall=round(result.recall, 3),
        precision=round(result.precision, 3),
        f1=round(result.f1, 3),
        avg_brier=round(result.avg_brier_score, 4),
        avg_brier_skill=round(result.avg_brier_skill_score, 4),
        avg_auc=round(result.avg_auc, 4),
        known_crises_detected=sum(1 for v in result.known_crisis_validations if v["met_target"]),
    )

    return result
