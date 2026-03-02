"""Bayesian fusion model — NumPyro/JAX for principled uncertainty quantification.

Stage 3b of the FRR pipeline:
    LSTM predictions + prior knowledge → Bayesian inference → calibrated P(crisis) with CI

Uses NUTS (No-U-Turn Sampler) for posterior inference.
This provides calibrated confidence intervals that the LSTM alone cannot give.
"""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    import jax
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    from numpyro.infer import MCMC, NUTS, Predictive

    HAS_NUMPYRO = True
except ImportError:
    HAS_NUMPYRO = False

import structlog

from frr.config import get_settings

logger = structlog.get_logger(__name__)


def crisis_probability_model(
    features: Any = None,
    labels: Any = None,
    num_crisis_types: int = 5,
) -> None:
    """NumPyro generative model for crisis probability.

    Bayesian logistic regression with informative priors:
    - Weights have a Normal(0, 1) prior (regularised)
    - Bias has a Normal(-2, 1) prior (crises are rare — base rate ~5%)

    Parameters
    ----------
    features : jnp.ndarray [N, D]
        Feature matrix (e.g. from LSTM embeddings + anomaly z-scores).
    labels : jnp.ndarray [N, K], optional
        Binary crisis labels (for training). None during prediction.
    num_crisis_types : int
        Number of crisis output categories.
    """
    if not HAS_NUMPYRO:
        raise ImportError("numpyro + jax are required for Bayesian fusion")

    D = features.shape[1] if features is not None else 1

    # Priors
    weights = numpyro.sample(
        "weights",
        dist.Normal(jnp.zeros((D, num_crisis_types)), jnp.ones((D, num_crisis_types))),
    )
    bias = numpyro.sample(
        "bias",
        dist.Normal(-2.0 * jnp.ones(num_crisis_types), jnp.ones(num_crisis_types)),
    )

    # Likelihood
    logits = jnp.matmul(features, weights) + bias
    probs = jax.nn.sigmoid(logits)

    with numpyro.plate("data", features.shape[0]):
        numpyro.sample(
            "obs",
            dist.Bernoulli(probs=probs),
            obs=labels,
        )


class BayesianFusion:
    """Wrapper around NumPyro MCMC for crisis probability inference."""

    def __init__(self) -> None:
        if not HAS_NUMPYRO:
            raise ImportError("numpyro + jax required")
        settings = get_settings()
        self.num_samples = settings.model_bayesian_num_samples
        self.num_warmup = settings.model_bayesian_num_warmup
        self.mcmc: MCMC | None = None
        self._rng_key = jax.random.PRNGKey(42)

    def fit(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        num_crisis_types: int = 5,
    ) -> None:
        """Run NUTS sampler to obtain posterior samples."""
        features_jax = jnp.array(features)
        labels_jax = jnp.array(labels)

        kernel = NUTS(crisis_probability_model)
        self.mcmc = MCMC(kernel, num_warmup=self.num_warmup, num_samples=self.num_samples)
        self.mcmc.run(
            self._rng_key,
            features=features_jax,
            labels=labels_jax,
            num_crisis_types=num_crisis_types,
        )
        logger.info(
            "Bayesian fusion training complete",
            num_samples=self.num_samples,
            num_warmup=self.num_warmup,
        )

    def predict(
        self,
        features: np.ndarray,
        num_crisis_types: int = 5,
    ) -> dict[str, np.ndarray]:
        """Generate posterior predictive samples.

        Returns
        -------
        dict with keys:
            - mean : [N, K] mean predicted probability
            - lower : [N, K] 5th percentile
            - upper : [N, K] 95th percentile
            - samples : [S, N, K] raw posterior samples
        """
        if self.mcmc is None:
            raise RuntimeError("Model not fit — call fit() first")

        features_jax = jnp.array(features)
        predictive = Predictive(
            crisis_probability_model,
            self.mcmc.get_samples(),
        )
        self._rng_key, subkey = jax.random.split(self._rng_key)
        predictions = predictive(
            subkey,
            features=features_jax,
            num_crisis_types=num_crisis_types,
        )

        obs = np.array(predictions["obs"])  # [S, N, K]
        return {
            "mean": obs.mean(axis=0),
            "lower": np.percentile(obs, 5, axis=0),
            "upper": np.percentile(obs, 95, axis=0),
            "samples": obs,
        }
