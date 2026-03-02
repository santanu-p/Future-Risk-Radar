"""Layer 4 — Spatial Propagation: crisis contagion via diffusion on weighted graph.

When CESI spikes in region A, adjacent/linked regions receive a propagated
boost based on weighted graph edges:

    ΔCESI_B = β × w_AB × CESI_A      (damped by distance)

Edge weights combine:
- Bilateral trade volume (UN Comtrade)
- Geographic proximity (haversine)
- Financial linkage (BIS banking statistics — approximated for MVP)

The diffusion process runs multiple hops to model cascading contagion:
- Hop 1: direct trade partners
- Hop 2: partners-of-partners (attenuated by β²)
- Hop 3+: systemic contagion (further attenuated)

This captures patterns like: MENA energy crisis → EU economic stress → LATAM
commodity shock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# ── MVP Region Definitions ────────────────────────────────────────────
REGION_CODES = ["EU", "MENA", "EAST_ASIA", "SOUTH_ASIA", "LATAM"]
NUM_REGIONS = len(REGION_CODES)

CENTROIDS: dict[str, tuple[float, float]] = {
    "EU": (50.1, 9.7),
    "MENA": (29.0, 41.0),
    "EAST_ASIA": (35.0, 120.0),
    "SOUTH_ASIA": (23.0, 80.0),
    "LATAM": (-15.0, -60.0),
}

# Bilateral trade flow weights (row=source, col=dest) — from UN Comtrade aggregates
# Normalised so each row sums to ≈1.0
TRADE_MATRIX = np.array(
    [
        #  EU    MENA   EASIA  SASIA  LATAM
        [0.00, 0.18, 0.35, 0.12, 0.10],  # EU exports
        [0.25, 0.00, 0.28, 0.15, 0.04],  # MENA exports
        [0.28, 0.14, 0.00, 0.20, 0.10],  # EAST_ASIA exports
        [0.14, 0.22, 0.25, 0.00, 0.05],  # SOUTH_ASIA exports
        [0.16, 0.05, 0.18, 0.06, 0.00],  # LATAM exports
    ],
    dtype=np.float64,
)

# Financial linkage weights (BIS cross-border banking claims approximation)
FINANCIAL_MATRIX = np.array(
    [
        #  EU    MENA   EASIA  SASIA  LATAM
        [0.00, 0.12, 0.30, 0.08, 0.15],  # EU
        [0.20, 0.00, 0.15, 0.10, 0.03],  # MENA
        [0.22, 0.08, 0.00, 0.12, 0.06],  # EAST_ASIA
        [0.10, 0.15, 0.18, 0.00, 0.04],  # SOUTH_ASIA
        [0.18, 0.03, 0.10, 0.05, 0.00],  # LATAM
    ],
    dtype=np.float64,
)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    la1, la2, lo1, lo2 = map(math.radians, [lat1, lat2, lon1, lon2])
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ── Build combined adjacency matrix ──────────────────────────────────

def build_adjacency_matrix(
    trade_weight: float = 0.4,
    financial_weight: float = 0.3,
    geographic_weight: float = 0.3,
) -> np.ndarray:
    """Build a combined [R, R] adjacency matrix from trade, financial, and geographic channels.

    Each channel is normalised to [0, 1] before weighting.
    """
    # Geographic proximity matrix (inverse distance, normalised)
    geo = np.zeros((NUM_REGIONS, NUM_REGIONS))
    for i, ci in enumerate(REGION_CODES):
        for j, cj in enumerate(REGION_CODES):
            if i != j:
                geo[i, j] = _haversine_km(*CENTROIDS[ci], *CENTROIDS[cj])
    max_d = geo.max() if geo.max() > 0 else 1.0
    geo_normed = 1.0 - geo / max_d  # closer → higher weight
    np.fill_diagonal(geo_normed, 0.0)

    # Normalise trade and financial matrices by their max
    trade_normed = TRADE_MATRIX / (TRADE_MATRIX.max() or 1.0)
    fin_normed = FINANCIAL_MATRIX / (FINANCIAL_MATRIX.max() or 1.0)

    combined = (
        trade_weight * trade_normed
        + financial_weight * fin_normed
        + geographic_weight * geo_normed
    )
    # Row-normalise
    row_sums = combined.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    combined /= row_sums

    return combined


# ── Propagation ───────────────────────────────────────────────────────

@dataclass
class PropagationResult:
    """Result of spatial propagation for all regions."""

    original_scores: dict[str, float]
    propagated_scores: dict[str, float]
    delta: dict[str, float]
    contagion_details: list[dict[str, Any]] = field(default_factory=list)


def propagate_scores(
    cesi_scores: dict[str, float],
    beta: float = 0.15,
    num_hops: int = 3,
    damping: float = 0.6,
    trade_weight: float = 0.4,
    financial_weight: float = 0.3,
    geographic_weight: float = 0.3,
) -> PropagationResult:
    """Run multi-hop diffusion to propagate crisis stress across regions.

    Parameters
    ----------
    cesi_scores : dict[region_code → CESI score (0-100)]
    beta : float
        Base transmission rate per hop.
    num_hops : int
        Number of propagation hops (1=direct, 2=partner-of-partner, 3+=systemic).
    damping : float
        Per-hop attenuation factor: effective β at hop k = beta × damping^(k-1).
    trade_weight, financial_weight, geographic_weight : float
        Channel weights for the adjacency matrix.

    Returns
    -------
    PropagationResult with original, propagated scores, and contagion details.
    """
    adj = build_adjacency_matrix(trade_weight, financial_weight, geographic_weight)

    # Convert scores to vector
    scores = np.array([cesi_scores.get(c, 0.0) for c in REGION_CODES], dtype=np.float64)
    original = scores.copy()
    contagion_details: list[dict[str, Any]] = []

    for hop in range(1, num_hops + 1):
        effective_beta = beta * (damping ** (hop - 1))

        # Compute spillover: Δ = effective_beta × (adj^T @ scores)
        # adj^T because if MENA exports stress, EU (column) receives it
        incoming = adj.T @ scores  # [R] — total incoming risk per region
        delta = effective_beta * incoming

        # Only propagate from spiking regions (CESI > 40 = "Elevated+")
        spike_mask = scores > 40.0
        if not spike_mask.any():
            break

        # Mask non-spiking sources in the adjacency
        adj_masked = adj.copy()
        for i in range(NUM_REGIONS):
            if not spike_mask[i]:
                adj_masked[i, :] = 0.0

        incoming_masked = adj_masked.T @ scores
        delta = effective_beta * incoming_masked

        contagion_details.append({
            "hop": hop,
            "effective_beta": round(effective_beta, 4),
            "spiking_regions": [REGION_CODES[i] for i in range(NUM_REGIONS) if spike_mask[i]],
            "delta_per_region": {REGION_CODES[i]: round(float(delta[i]), 3) for i in range(NUM_REGIONS)},
        })

        scores = scores + delta

    # Clamp to [0, 100]
    scores = np.clip(scores, 0.0, 100.0)

    result = PropagationResult(
        original_scores={REGION_CODES[i]: float(original[i]) for i in range(NUM_REGIONS)},
        propagated_scores={REGION_CODES[i]: float(scores[i]) for i in range(NUM_REGIONS)},
        delta={REGION_CODES[i]: float(scores[i] - original[i]) for i in range(NUM_REGIONS)},
        contagion_details=contagion_details,
    )

    logger.info(
        "Spatial propagation complete",
        hops=num_hops,
        beta=beta,
        max_delta=round(max(result.delta.values()), 2) if result.delta else 0.0,
    )

    return result


def propagate_crisis_probabilities(
    crisis_probs: dict[str, np.ndarray],
    beta: float = 0.10,
    num_hops: int = 2,
    damping: float = 0.5,
) -> dict[str, np.ndarray]:
    """Propagate per-crisis-type probabilities across regions.

    Parameters
    ----------
    crisis_probs : dict[region_code → ndarray of shape [5] (probabilities)]

    Returns updated dict with propagated probabilities.
    """
    adj = build_adjacency_matrix()
    num_types = 5

    # Stack into [R, 5] matrix
    prob_matrix = np.zeros((NUM_REGIONS, num_types), dtype=np.float64)
    for i, code in enumerate(REGION_CODES):
        if code in crisis_probs:
            prob_matrix[i, :] = crisis_probs[code][:num_types]

    for hop in range(1, num_hops + 1):
        effective_beta = beta * (damping ** (hop - 1))
        incoming = adj.T @ prob_matrix  # [R, 5]
        prob_matrix = prob_matrix + effective_beta * incoming

    # Clamp to [0, 1]
    prob_matrix = np.clip(prob_matrix, 0.0, 1.0)

    return {REGION_CODES[i]: prob_matrix[i] for i in range(NUM_REGIONS)}
