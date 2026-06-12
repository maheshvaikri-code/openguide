"""GridRuntime: evaluates one grid column per step against hidden states.

 - norm-preserving injection: h' = (h + g·v) · (‖h‖ / ‖h + g·v‖)
 - Σ-cap enforced mechanically (not advisory): columns scale down, recorded
 - control channel: set_gain / fire trigger — every mutation appends to trace
"""
from __future__ import annotations
import numpy as np
from .grid import Grid, SignalPack
from .trace import Trace


def inject(h: np.ndarray, v: np.ndarray, gain: float, preserve_norm: bool = True) -> np.ndarray:
    out = h + np.float32(gain) * v
    if preserve_norm:
        n0 = np.linalg.norm(h)
        n1 = np.linalg.norm(out)
        if n1 > 1e-9:
            out = out * np.float32(n0 / n1)
    return out


class GridRuntime:
    def __init__(self, grid: Grid, pack: SignalPack, manifest: dict, sigma_cap: float = 1.25):
        self.grid = grid
        self.pack = pack
        self.sigma_cap = float(sigma_cap)
        self.overrides: dict[str, float] = {}  # live gain multipliers
        self.trace = Trace(manifest)
        self.triggers = {t["on"]: t["apply"] for t in manifest.get("spec", {}).get("triggers", [])}

    # ── control channel (ring-0: every write is recorded) ────────────
    def set_gain(self, signal: str, multiplier: float, t: int, source: str = "operator"):
        old = self.overrides.get(signal, 1.0)
        self.overrides[signal] = float(multiplier)
        self.trace.append(
            {"step": t, "ev": "OVERRIDE", "signal": signal, "old": old, "new": float(multiplier), "source": source}
        )

    def fire(self, trigger: str, t: int, source: str = "runtime"):
        ap = self.triggers.get(trigger)
        if ap is None:
            raise KeyError(f"unknown trigger: {trigger}")
        f = self.grid.field(ap["signal"])
        l_lo, l_hi = ap["layers"]
        f.write_decay(l_lo, l_hi, t, ap["g"], ap["tau"], ap.get("horizon", 48))
        self.trace.append(
            {"step": t, "ev": "TRIGGER", "on": trigger, "signal": ap["signal"],
             "g": float(ap["g"]), "tau": float(ap["tau"]), "layers": [l_lo, l_hi], "source": source}
        )

    # ── per-step evaluation ──────────────────────────────────────────
    def apply(self, h: np.ndarray, t: int) -> np.ndarray:
        """h: (L, d) hidden states. Returns injected states; records the step."""
        L, d = h.shape
        cols = self.grid.column(t)
        # live knob multipliers
        cols = {s: c * np.float32(self.overrides.get(s, 1.0)) for s, c in cols.items()}

        # Σ-cap: mechanical, per-layer
        total = np.zeros(L, dtype=np.float32)
        for c in cols.values():
            total += np.abs(c)
        peak = float(total.max()) if len(cols) else 0.0
        scale = self.sigma_cap / peak if peak > self.sigma_cap else 1.0

        out = h.copy()
        applied = {}
        for sig, col in cols.items():
            gains = []
            for l in range(L):
                g = float(col[l]) * scale
                if abs(g) < 1e-4:
                    continue
                v = self.pack.get(sig, l)
                if v is None:
                    continue
                out[l] = inject(out[l], v, g)
                gains.append([l, round(g, 6)])
            if gains:
                applied[sig] = gains

        self.trace.append(
            {"step": t, "ev": "STEP", "applied": applied,
             "sigma_peak": round(peak, 6), "norm_corr": round(1.0 - scale, 6)}
        )
        return out
