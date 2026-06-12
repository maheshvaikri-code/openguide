"""Grid tuning: the grid as a learnable parameter.

Toy plant (leaky drift dynamics, analytic gradient — no autograd needed):

    a(t+1) = a(t) + leak*(a0 - a(t)) - drift(t) + k * u(t)
    u(t)   = p[t // W]                      per-frame grid gain (the params)

Interventions fade with horizon ~1/leak steps, so holding adherence against
late-growing drift requires *late* gain — the learned schedule must ramp.

Objective (measurable setpoint, never prose):

    J(p) = Sum_t max(0, target - a(t))^2  +  lam * Sum_t u(t)^2
           |--- hold adherence >= target --|   |-- capability tax --|

Exact gradient:  da(t)/du(s) = k * (1-leak)^(t-1-s)  for s < t.

Result: the learned grid finds the minimal sufficient intervention —
it spends gain only where drift demands it, beating any constant gain
at equal adherence.
"""
from __future__ import annotations
import numpy as np

A0, LEAK, K = 0.92, 0.06, 0.01


def default_drift(T: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    d = 0.012 * (np.arange(T) / T) ** 1.2 + 0.0004 * rng.standard_normal(T)
    return np.clip(d, 0.0, None)


def simulate(p: np.ndarray, T: int, W: int, drift: np.ndarray,
             a0: float = A0, leak: float = LEAK, k: float = K) -> np.ndarray:
    a = np.empty(T + 1, dtype=np.float64)
    a[0] = a0
    for t in range(T):
        a[t + 1] = a[t] + leak * (a0 - a[t]) - drift[t] + k * p[t // W]
    return a


def grid_tune(T: int = 96, W: int = 16, target: float = 0.85,
              lam: float = 0.0005, iters: int = 2000, lr: float = 3.0, seed: int = 7):
    drift = default_drift(T, seed)
    F = T // W
    p = np.zeros(F, dtype=np.float64)            # init: no intervention

    # influence[f, t-1] = k * sum_{s in frame f, s < t} (1-leak)^(t-1-s)
    influence = np.zeros((F, T))
    for f in range(F):
        for t in range(1, T + 1):
            s_hi = min(t, (f + 1) * W)
            if s_hi <= f * W:
                continue
            exps = (t - 1) - np.arange(f * W, s_hi)
            influence[f, t - 1] = K * np.sum((1.0 - LEAK) ** exps)

    losses = []
    for _ in range(iters):
        a = simulate(p, T, W, drift)
        deficit = np.maximum(0.0, target - a[1:])
        J = float(np.sum(deficit ** 2) + lam * np.sum(p[np.arange(T) // W] ** 2))
        losses.append(J)
        grad = influence @ (-2.0 * deficit) + 2.0 * lam * W * p
        p = np.clip(p - lr * grad, 0.0, 1.0)

    a = simulate(p, T, W, drift)
    return {
        "params": p, "losses": losses, "adherence": a, "drift": drift,
        "final_adherence": float(a[-1]), "min_adherence": float(a[1:].min()),
        "mean_gain": float(p[np.arange(T) // W].mean()),
    }


def constant_baseline(T: int, W: int, target: float, drift: np.ndarray):
    """Smallest constant gain that holds adherence >= target throughout."""
    for g in np.linspace(0, 1, 2001):
        a = simulate(np.full(T // W, g), T, W, drift)
        if a[1:].min() >= target:
            return float(g), a
    return 1.0, simulate(np.ones(T // W), T, W, drift)
