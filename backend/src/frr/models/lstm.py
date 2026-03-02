"""LSTM temporal model for time-series crisis probability forecasting.

Stage 3a of the FRR pipeline:
    region embeddings (GAT) + historical features → LSTM → P(crisis | next 12 months)

Input: sequence of monthly feature vectors (GAT embedding + raw indicators)
Output: probability per crisis type for the forecast horizon
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn


class CrisisLSTM(nn.Module):
    """Bidirectional LSTM for crisis probability prediction.

    Architecture:
        InputProjection → BiLSTM(2 layers) → Attention → FC → Sigmoid (5 crisis types)

    Parameters
    ----------
    input_dim : int
        Feature dimension per timestep (GAT embedding + raw indicators).
    hidden_dim : int
        LSTM hidden state dimension.
    num_layers : int
        Number of stacked LSTM layers.
    num_crisis_types : int
        Number of output crisis categories (default 5).
    dropout : float
        Dropout between LSTM layers and in the classifier head.
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int = 128,
        num_layers: int = 2,
        num_crisis_types: int = 5,
        dropout: float = 0.3,
    ) -> None:
        super().__init__()

        self.input_proj = nn.Linear(input_dim, hidden_dim)
        self.lstm = nn.LSTM(
            input_size=hidden_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Temporal attention — learn which timesteps matter most
        self.attention = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1, bias=False),
        )

        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, num_crisis_types),
        )

    def forward(self, x: Tensor) -> Tensor:
        """Forward pass.

        Parameters
        ----------
        x : Tensor [batch, seq_len, input_dim]
            Sequence of monthly feature vectors.

        Returns
        -------
        Tensor [batch, num_crisis_types]
            Probability per crisis type (after sigmoid).
        """
        # Project input
        x = self.input_proj(x)
        x = F.relu(x)

        # BiLSTM
        lstm_out, _ = self.lstm(x)  # [batch, seq_len, hidden*2]

        # Temporal attention
        attn_weights = self.attention(lstm_out)  # [batch, seq_len, 1]
        attn_weights = F.softmax(attn_weights, dim=1)
        context = torch.sum(attn_weights * lstm_out, dim=1)  # [batch, hidden*2]

        # Classify
        logits = self.classifier(context)  # [batch, num_crisis_types]
        return torch.sigmoid(logits)


class CrisisLSTMWithUncertainty(CrisisLSTM):
    """Extension with MC Dropout for uncertainty estimation.

    At inference time, run multiple forward passes with dropout enabled
    to get a distribution of predictions → confidence intervals.
    """

    def predict_with_uncertainty(
        self,
        x: Tensor,
        num_samples: int = 50,
    ) -> tuple[Tensor, Tensor, Tensor]:
        """Run MC Dropout inference.

        Returns
        -------
        mean : Tensor [batch, num_crisis_types]
            Mean predicted probability.
        lower : Tensor [batch, num_crisis_types]
            5th percentile (90% CI lower bound).
        upper : Tensor [batch, num_crisis_types]
            95th percentile (90% CI upper bound).
        """
        self.train()  # Enable dropout
        predictions = []

        with torch.no_grad():
            for _ in range(num_samples):
                pred = self.forward(x)
                predictions.append(pred)

        preds = torch.stack(predictions, dim=0)  # [num_samples, batch, crisis_types]
        mean = preds.mean(dim=0)
        lower = preds.quantile(0.05, dim=0)
        upper = preds.quantile(0.95, dim=0)

        self.eval()
        return mean, lower, upper
