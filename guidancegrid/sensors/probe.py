"""Linear probe sensor: read behavioral state off the residual stream.

A probe is a linear classifier trained on labeled contrast activations at one
layer (adherent vs not). At inference it scores the current residual vector ->
an adherence reading in [0,1]. This is the ``probe:`` measure kind, available
only on the T0 (open-weight) tier where the residual stream is observable.

Deterministic given fixed weights. Training is offline (scikit-learn logistic
regression); only the dot-product score runs in the hot loop.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from .base import Measure


class LinearProbe:
    """A single-layer linear probe: sigmoid(w·x + b) in [0,1]."""

    def __init__(self, layer: int, w: np.ndarray, b: float):
        self.layer = int(layer)
        self.w = np.asarray(w, dtype=np.float32)
        self.b = float(b)

    def score(self, x: np.ndarray) -> float:
        z = float(np.dot(self.w, np.asarray(x, dtype=np.float32)) + self.b)
        return float(1.0 / (1.0 + np.exp(-z)))

    # ── training (offline) ───────────────────────────────────────────
    @classmethod
    def train(cls, layer: int, pos: np.ndarray, neg: np.ndarray,
              C: float = 1.0, seed: int = 0) -> "LinearProbe":
        """Fit on labeled activations. pos/neg: (n, d) residual vectors at
        ``layer`` for adherent / non-adherent examples."""
        from sklearn.linear_model import LogisticRegression

        X = np.vstack([pos, neg]).astype(np.float64)
        y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
        clf = LogisticRegression(C=C, max_iter=1000, random_state=seed)
        clf.fit(X, y)
        return cls(layer, clf.coef_[0].astype(np.float32), float(clf.intercept_[0]))

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "w": self.w.tolist(), "b": self.b}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LinearProbe":
        return cls(d["layer"], np.asarray(d["w"], dtype=np.float32), d["b"])


class ProbeMeasure(Measure):
    """A probe:<name> measure. Reads ctx[residual_key][probe.layer] -> score.

    The harness places the per-layer residual vectors for the turn on the
    context under ``residual_key`` (e.g. captured by a forward hook). Missing
    residuals read as a sensor gap.
    """

    determinism = "deterministic"
    latency_class = "fast"

    def __init__(self, measure_id: str, probe: LinearProbe,
                 residual_key: str = "residual",
                 extractor: Callable[[dict[str, Any]], np.ndarray | None] | None = None):
        super().__init__(measure_id)
        self.probe = probe
        self.residual_key = residual_key
        self.extractor = extractor

    def _read(self, ctx: dict[str, Any]) -> float | None:
        if self.extractor is not None:
            x = self.extractor(ctx)
        else:
            residuals = ctx.get(self.residual_key)
            if residuals is None:
                return None
            x = residuals.get(self.probe.layer) if isinstance(residuals, dict) else None
        if x is None:
            return None
        return self.probe.score(np.asarray(x))
