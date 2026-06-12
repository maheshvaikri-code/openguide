"""T0: activation steering via PyTorch forward hooks (open-weight enforcement).

The strongest tier. A forward hook on each decoder layer injects the layer's
steering vector into the residual stream, scaled by the grid's gain at the
current (layer, step) and capped by the mechanical Σ-cap. Norm-preserving
injection keeps the hidden-state magnitude unchanged (literature-validated:
Selective Steering, arXiv:2601.19375), so only the *direction* moves.

torch is an optional dependency — import this module only when steering
open weights. Everything is recorded to a Trace, so a T0 run is replay-identical
exactly like the numpy reference runtime.

Design note: layers fire in order 0..L-1 on every forward pass, so layer 0's
hook opens a step (computes the column + Σ-cap scale) and the last layer's hook
closes it (records + advances t). That advances one step per generated token
without the caller threading a counter through `generate()`.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import torch

from ..core.grid import Grid, SignalPack
from ..core.trace import Trace


def inject_torch(h: torch.Tensor, v: torch.Tensor, gain: float,
                 preserve_norm: bool = True) -> torch.Tensor:
    """Norm-preserving residual injection over the last dim. h:(...,d) v:(d,)."""
    out = h + float(gain) * v
    if preserve_norm:
        n0 = h.norm(dim=-1, keepdim=True)
        n1 = out.norm(dim=-1, keepdim=True).clamp_min(1e-9)
        out = out * (n0 / n1)
    return out


def decoder_layers(model: Any) -> list[Any]:
    """Best-effort lookup of the decoder layer modules for common HF archs."""
    for path in ("model.layers", "model.model.layers", "transformer.h",
                 "gpt_neox.layers", "model.decoder.layers"):
        obj = model
        try:
            for attr in path.split("."):
                obj = getattr(obj, attr)
            return list(obj)
        except AttributeError:
            continue
    raise AttributeError("could not locate decoder layers; pass them explicitly")


class ActivationSteerer:
    """Registers forward hooks that steer the residual stream per (layer, step)."""

    def __init__(self, grid: Grid, pack: SignalPack, manifest: dict[str, Any],
                 sigma_cap: float = 1.25, num_layers: int | None = None):
        self.grid = grid
        self.pack = pack
        self.sigma_cap = float(sigma_cap)
        self.trace = Trace(manifest)
        self.L = int(num_layers or grid.L)
        self.overrides: dict[str, float] = {}
        self.t = 0
        self._handles: list[Any] = []
        self._vec_cache: dict[tuple, torch.Tensor | None] = {}
        self._col: dict[int, dict[str, float]] = {}
        self._scale = 1.0
        self._peak = 0.0
        self._applied: dict[str, list] = {}

    # ── step lifecycle (driven by layer-0 / last-layer hooks) ────────
    def _begin_step(self) -> None:
        col: dict[int, dict[str, float]] = {}
        total = np.zeros(self.L, dtype=np.float64)
        for name, field in self.grid.fields.items():
            mult = self.overrides.get(name, 1.0)
            for l in range(self.L):
                g = field.get(l, self.t) * mult
                if abs(g) > 1e-9:
                    col.setdefault(l, {})[name] = g
                    total[l] += abs(g)
        peak = float(total.max()) if total.size else 0.0
        self._scale = self.sigma_cap / peak if peak > self.sigma_cap else 1.0
        self._col, self._peak, self._applied = col, peak, {}

    def _end_step(self) -> None:
        self.trace.append({
            "step": self.t, "ev": "STEP", "applied": self._applied,
            "sigma_peak": round(self._peak, 6), "norm_corr": round(1.0 - self._scale, 6),
        })
        self.t += 1

    def _vector(self, name: str, layer: int, ref: torch.Tensor) -> torch.Tensor | None:
        key = (name, layer, ref.device, ref.dtype)
        if key not in self._vec_cache:
            v = self.pack.get(name, layer)
            self._vec_cache[key] = (
                None if v is None else torch.as_tensor(np.asarray(v), dtype=ref.dtype, device=ref.device)
            )
        return self._vec_cache[key]

    def _hook(self, layer: int):
        def fn(module, inputs, output):
            if layer == 0:
                self._begin_step()
            h = output[0] if isinstance(output, tuple) else output
            for name, g in self._col.get(layer, {}).items():
                v = self._vector(name, layer, h)
                if v is None:
                    continue
                gg = g * self._scale
                h = inject_torch(h, v, gg)
                self._applied.setdefault(name, []).append([layer, round(float(gg), 6)])
            if layer == self.L - 1:
                self._end_step()
            if isinstance(output, tuple):
                return (h, *output[1:])
            return h
        return fn

    # ── registration ─────────────────────────────────────────────────
    def register(self, layers: list[Any] | None = None, model: Any | None = None) -> "ActivationSteerer":
        if layers is None:
            layers = decoder_layers(model)
        self.L = len(layers)
        for i, mod in enumerate(layers):
            self._handles.append(mod.register_forward_hook(self._hook(i)))
        return self

    def remove(self) -> None:
        for h in self._handles:
            h.remove()
        self._handles = []

    def __enter__(self) -> "ActivationSteerer":
        return self

    def __exit__(self, *exc) -> None:
        self.remove()

    # ── control channel (every write recorded) ───────────────────────
    def set_gain(self, signal: str, multiplier: float, source: str = "operator") -> None:
        old = self.overrides.get(signal, 1.0)
        self.overrides[signal] = float(multiplier)
        self.trace.append({"step": self.t, "ev": "OVERRIDE", "signal": signal,
                           "old": old, "new": float(multiplier), "source": source})
