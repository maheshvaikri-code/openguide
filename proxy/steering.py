"""Drift-gated activation steering (T0) for a proxy that owns the model's weights. See ADR-003.

The Governor steers the *next* generation of a session after a turn whose recovery action fired, and
not otherwise. This module holds only the settings and the one decision; the hooks themselves are
``guidancegrid.channels.t0_activation`` (imported lazily by ``HFUpstream.enable_steering``, so a proxy
that does not steer never needs torch).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from guidancegrid.core.grid import STEER_SIGNAL, SignalPack

# The largest gain measured to leave the model usable (benchmarks/REPORT.md 7.2: 0.2 and above produce
# degenerate output). A code constant on purpose: raising it is a decision, not a setting.
MAX_SAFE_GAIN = 0.1
DEFAULT_GAIN = 0.05
# A pack vector may be at most this many times the model's typical residual norm (derive makes it 1x).
# The gain bounds the push only if the vector is on the model's own scale: injection is renormalised to the
# hidden state's norm, so a vector that dwarfs it would replace the state whatever the gain.
MAX_VECTOR_NORM_RATIO = 4.0


@dataclass
class SteerReceipt:
    """What an upstream reports back about one steered call. The Governor never assumes steering happened: it
    records a STEER only once the upstream says a steered reply was produced."""
    gain: float
    produced: bool = False     # set by the upstream once a reply was generated with steering on
    recorded: bool = False     # set by the Governor once the trace holds the STEER for it


@dataclass(frozen=True)
class SteeringConfig:
    pack: SignalPack
    band: tuple[int, int]               # decoder layers lo..hi-1 that are steered
    gain: float = DEFAULT_GAIN          # the PEAK of a gaussian envelope across the band (edges get less)
    expected_pack_hash: str | None = None      # pin the pack the operator reviewed; refuse any other

    def __post_init__(self) -> None:
        g = self.gain
        ok = isinstance(g, (int, float)) and math.isfinite(g) and 0 < g <= MAX_SAFE_GAIN
        if not ok:
            raise ValueError(
                f"steering gain must be above 0 and at most {MAX_SAFE_GAIN} (larger gains were measured to "
                f"break the model's output), got {self.gain!r}")
        lo, hi = self.band
        if not (0 <= lo < hi):
            raise ValueError(f"steering band must be layers with 0 <= lo < hi, got {self.band!r}")
        missing = [layer for layer in range(lo, hi) if self.pack.get(STEER_SIGNAL, layer) is None]
        if missing:
            raise ValueError(f"the steering pack has no direction for layer(s) {missing} in band {self.band}")
        for layer in range(lo, hi):
            v = np.asarray(self.pack.get(STEER_SIGNAL, layer))
            if v.shape != (self.pack.d,) or not np.all(np.isfinite(v)):
                finite = bool(np.all(np.isfinite(v)))
                raise ValueError(f"the steering pack's vector at layer {layer} must be a finite flat vector "
                                 f"of length {self.pack.d} (got shape {v.shape}, finite={finite})")
        if self.expected_pack_hash is not None and self.expected_pack_hash != self.pack.hash():
            raise ValueError(f"the steering pack's hash is {self.pack.hash()}, not the pinned "
                             f"{self.expected_pack_hash}")

    def pack_in_band(self) -> SignalPack:
        """A copy of the pack holding only the band's layers, so nothing outside the band is steered."""
        out = SignalPack(self.pack.model_id, self.pack.d)
        for layer in range(*self.band):
            out.set_vector(STEER_SIGNAL, layer, np.asarray(self.pack.get(STEER_SIGNAL, layer)))
        return out

    @property
    def pack_hash(self) -> str:
        return self.pack.hash()

    def manifest(self, model_name: str) -> dict[str, Any]:
        return {"model": model_name, "pack_hash": self.pack_hash, "runtime": "openguide-proxy-steering"}


def wants_steering(action: str | None) -> bool:
    """Steer the next generation iff this turn's recovery action fired (the trigger of a T2 re-anchor)."""
    return action is not None
