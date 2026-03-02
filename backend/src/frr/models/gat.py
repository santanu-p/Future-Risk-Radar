"""Graph Attention Network (GAT) for inter-region contagion modelling.

Stage 2 of the FRR pipeline:
    anomaly embeddings → GAT → region-aware risk embeddings

Graph structure:
- Nodes = (regions × signal layers) — heterogeneous graph
- Edges:
  - Same-region cross-layer connections  (EU-patents ↔ EU-supply_chain)
  - Same-layer cross-region connections  (EU-energy  ↔ MENA-energy)
  - Trade / geographic adjacency edges
- Node features = anomaly z-score vectors from Stage 1

The GAT learns attention weights that capture how stress in one region
(e.g. energy shock in MENA) propagates to dependent regions (e.g. EU).
Non-linear amplification emerges when 3+ layers spike simultaneously
because attention weights compound across multi-hop paths.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import torch
import torch.nn.functional as F
from torch import Tensor, nn

try:
    from torch_geometric.nn import GATConv
    HAS_PYG = True
except ImportError:
    HAS_PYG = False

# ── MVP region codes (order matters — used as node indices) ────────────
MVP_REGION_CODES: list[str] = ["EU", "MENA", "EAST_ASIA", "SOUTH_ASIA", "LATAM"]

# Approximate geographic centroids for distance computation
_CENTROIDS: dict[str, tuple[float, float]] = {
    "EU": (50.1, 9.7),
    "MENA": (29.0, 41.0),
    "EAST_ASIA": (35.0, 120.0),
    "SOUTH_ASIA": (23.0, 80.0),
    "LATAM": (-15.0, -60.0),
}

# Expert-sourced trade dependency weights (normalised).  Row=exporter, Col=importer
# Derived from UN Comtrade bilateral flows (top-level approximation).
_TRADE_DEPENDENCY: list[list[float]] = [
    #  EU    MENA  EASIA  SASIA  LATAM
    [0.00, 0.15, 0.30, 0.10, 0.08],  # EU
    [0.20, 0.00, 0.25, 0.10, 0.02],  # MENA
    [0.25, 0.12, 0.00, 0.18, 0.08],  # EAST_ASIA
    [0.10, 0.18, 0.20, 0.00, 0.03],  # SOUTH_ASIA
    [0.12, 0.03, 0.15, 0.04, 0.00],  # LATAM
]

SIGNAL_LAYERS = ["research_funding", "patent_activity", "supply_chain", "energy_conflict"]


# ───────────────────────────────────────────────────────────────────────
# Model
# ───────────────────────────────────────────────────────────────────────

class RegionGAT(nn.Module):
    """Multi-head Graph Attention Network for region risk propagation.

    Architecture:
        InputProjection → GATConv(heads=4) → ELU → GATConv(heads=1) → output embedding

    Parameters
    ----------
    in_features : int
        Dimension of input node features (= number of anomaly indicators per region).
    hidden_dim : int
        GAT hidden layer dimension per head.
    out_dim : int
        Output embedding dimension per region.
    heads : int
        Number of attention heads in the first GAT layer.
    dropout : float
        Dropout rate for attention coefficients.
    """

    def __init__(
        self,
        in_features: int,
        hidden_dim: int = 64,
        out_dim: int = 32,
        heads: int = 4,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        if not HAS_PYG:
            raise ImportError("torch-geometric is required for GAT model. Install with: pip install torch-geometric")

        self.in_features = in_features
        self.out_dim = out_dim

        self.input_proj = nn.Linear(in_features, hidden_dim)
        self.gat1 = GATConv(hidden_dim, hidden_dim, heads=heads, dropout=dropout, concat=True)
        self.gat2 = GATConv(hidden_dim * heads, out_dim, heads=1, dropout=dropout, concat=False)
        self.dropout = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(out_dim)

    def forward(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_attr: Optional[Tensor] = None,
    ) -> Tensor:
        """Forward pass.

        Parameters
        ----------
        x : Tensor [num_nodes, in_features]
            Node feature matrix (anomaly z-scores per region).
        edge_index : Tensor [2, num_edges]
            Graph connectivity in COO format.
        edge_attr : Tensor [num_edges, 1], optional
            Edge weights (trade dependency strength).

        Returns
        -------
        Tensor [num_nodes, out_dim]
            Region risk embeddings.
        """
        x = self.input_proj(x)
        x = F.elu(x)
        x = self.dropout(x)

        x = self.gat1(x, edge_index)
        x = F.elu(x)
        x = self.dropout(x)

        x = self.gat2(x, edge_index)
        x = self.norm(x)
        return x

    def get_attention_weights(
        self,
        x: Tensor,
        edge_index: Tensor,
    ) -> tuple[Tensor, Tensor]:
        """Return attention coefficients from both GAT layers (for explainability).

        Returns (attn1, attn2) tensors of shape [num_edges, heads].
        """
        h = self.input_proj(x)
        h = F.elu(h)
        _, attn1 = self.gat1(h, edge_index, return_attention_weights=True)
        h = self.gat1(h, edge_index)
        h = F.elu(h)
        _, attn2 = self.gat2(h, edge_index, return_attention_weights=True)
        return attn1[1], attn2[1]


class GATClassifier(nn.Module):
    """GAT encoder + classification head for supervised end-to-end training.

    Used in the training pipeline to jointly learn graph structure and
    predict per-region crisis probabilities.
    """

    def __init__(
        self,
        in_features: int,
        gat_hidden: int = 64,
        gat_out: int = 32,
        heads: int = 4,
        dropout: float = 0.2,
        num_crisis_types: int = 5,
    ) -> None:
        super().__init__()
        self.gat = RegionGAT(in_features, gat_hidden, gat_out, heads, dropout)
        self.head = nn.Sequential(
            nn.Linear(gat_out, gat_out),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(gat_out, num_crisis_types),
        )

    def forward(
        self,
        x: Tensor,
        edge_index: Tensor,
        edge_attr: Optional[Tensor] = None,
    ) -> Tensor:
        """Returns [num_nodes, num_crisis_types] logits."""
        embeddings = self.gat(x, edge_index, edge_attr)
        return self.head(embeddings)

    @property
    def encoder(self) -> RegionGAT:
        return self.gat


# ───────────────────────────────────────────────────────────────────────
# Graph construction utilities
# ───────────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points (km)."""
    R = 6371.0
    la1, la2, lo1, lo2 = map(math.radians, [lat1, lat2, lon1, lon2])
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = math.sin(dlat / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def build_region_graph(
    num_regions: int = 5,
    trade_weight: float = 0.5,
    geo_weight: float = 0.5,
) -> tuple[Tensor, Tensor]:
    """Build a weighted directed graph for MVP regions.

    Edge weight = trade_weight × trade_dependency + geo_weight × (1 / distance_norm).

    Returns (edge_index [2, E], edge_weight [E]).
    """
    # Distance matrix (normalised to [0, 1])
    codes = MVP_REGION_CODES[:num_regions]
    dist_matrix = np.zeros((num_regions, num_regions))
    for i, ci in enumerate(codes):
        for j, cj in enumerate(codes):
            if i != j:
                dist_matrix[i, j] = _haversine_km(*_CENTROIDS[ci], *_CENTROIDS[cj])
    max_dist = dist_matrix.max() if dist_matrix.max() > 0 else 1.0
    proximity = 1.0 - dist_matrix / max_dist  # closer → higher

    edges: list[list[int]] = []
    weights: list[float] = []
    for i in range(num_regions):
        for j in range(num_regions):
            if i != j:
                td = _TRADE_DEPENDENCY[i][j]
                gp = proximity[i, j]
                w = trade_weight * td + geo_weight * gp
                edges.append([i, j])
                weights.append(float(w))

    # Normalise weights to sum=1
    total = sum(weights) or 1.0
    weights = [w / total for w in weights]

    edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
    edge_weight = torch.tensor(weights, dtype=torch.float32)
    return edge_index, edge_weight


def build_heterogeneous_graph(
    num_regions: int = 5,
    num_layers: int = 4,
) -> tuple[Tensor, Tensor]:
    """Build a heterogeneous graph where nodes = regions × signal_layers.

    Node indexing: node_id = region_idx * num_layers + layer_idx

    Edges:
    - Same-region cross-layer (fully connected within a region's layers)
    - Same-layer cross-region (weighted by trade dependency)

    Returns (edge_index [2, E], edge_weight [E]).
    """
    num_nodes = num_regions * num_layers
    edges: list[list[int]] = []
    weights: list[float] = []

    for r in range(num_regions):
        # Intra-region cross-layer edges (bidirectional, uniform weight)
        for l1 in range(num_layers):
            for l2 in range(num_layers):
                if l1 != l2:
                    src = r * num_layers + l1
                    dst = r * num_layers + l2
                    edges.append([src, dst])
                    weights.append(1.0)

    for l in range(num_layers):
        # Inter-region same-layer edges (weighted by trade)
        for r1 in range(num_regions):
            for r2 in range(num_regions):
                if r1 != r2:
                    src = r1 * num_layers + l
                    dst = r2 * num_layers + l
                    td = _TRADE_DEPENDENCY[r1][r2]
                    edges.append([src, dst])
                    weights.append(td)

    total = sum(weights) or 1.0
    weights = [w / total for w in weights]

    edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
    edge_weight = torch.tensor(weights, dtype=torch.float32)
    return edge_index, edge_weight


def build_node_features_from_anomalies(
    anomaly_scores: dict[str, dict[str, float]],
    indicator_names: list[str],
    region_codes: list[str] | None = None,
) -> Tensor:
    """Convert per-region per-indicator anomaly z-scores into a feature matrix.

    Parameters
    ----------
    anomaly_scores : dict[region_code, dict[indicator, z_score]]
    indicator_names : list[str]
        Ordered list of indicator names (defines feature columns).
    region_codes : list[str] | None
        Region ordering. Defaults to MVP_REGION_CODES.

    Returns
    -------
    Tensor [num_regions, len(indicator_names)]
    """
    codes = region_codes or MVP_REGION_CODES
    features = []
    for code in codes:
        region_scores = anomaly_scores.get(code, {})
        row = [region_scores.get(ind, 0.0) for ind in indicator_names]
        features.append(row)
    return torch.tensor(features, dtype=torch.float32)
