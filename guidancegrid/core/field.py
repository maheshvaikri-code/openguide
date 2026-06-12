"""GainField: a literal grid.

A *total* scalar field over the (layer, step) lattice:
  - Totality: G[l, t] is defined for every coordinate; unset = 0.0.
  - Frames:   time is discretized into fixed-width frames; storage is a
              sparse dict of dense (L x W) float32 tiles. Sparse globally,
              dense locally (SIMD-friendly columns).
  - Algebra:  fields are closed under +, scalar *, mask, shift, crop.
"""
from __future__ import annotations

import numpy as np

from .canonical import chash


def gaussian_envelope(l_lo: int, l_hi: int, L: int) -> np.ndarray:
    """Layer envelope: gaussian centered on [l_lo, l_hi]."""
    c = (l_lo + l_hi) / 2.0
    w = max((l_hi - l_lo) / 2.2, 1e-6)
    ls = np.arange(L, dtype=np.float32)
    return np.exp(-(((ls - c) / w) ** 2)).astype(np.float32)


class GainField:
    def __init__(self, layers: int = 32, frame: int = 16):
        self.L = int(layers)
        self.W = int(frame)
        self.tiles: dict[int, np.ndarray] = {}

    # ── totality ─────────────────────────────────────────────────────
    def get(self, l: int, t: int) -> float:
        if not (0 <= l < self.L) or t < 0:
            raise IndexError(f"({l},{t}) outside lattice")
        tile = self.tiles.get(t // self.W)
        return float(tile[l, t % self.W]) if tile is not None else 0.0

    def column(self, t: int) -> np.ndarray:
        """One time-column of the grid: length-L gain vector at step t."""
        tile = self.tiles.get(t // self.W)
        if tile is None:
            return np.zeros(self.L, dtype=np.float32)
        return tile[:, t % self.W].copy()

    # ── writing ──────────────────────────────────────────────────────
    def _tile(self, fi: int) -> np.ndarray:
        tile = self.tiles.get(fi)
        if tile is None:
            tile = np.zeros((self.L, self.W), dtype=np.float32)
            self.tiles[fi] = tile
        return tile

    def add_column(self, t: int, col: np.ndarray) -> None:
        self._tile(t // self.W)[:, t % self.W] += col.astype(np.float32)

    def paint(self, l_lo: int, l_hi: int, t_lo: int, t_hi: int, fn) -> None:
        """Direct cell-level write over a region. fn(l, t) -> gain delta."""
        for t in range(t_lo, t_hi + 1):
            tile = self._tile(t // self.W)
            for l in range(l_lo, l_hi + 1):
                tile[l, t % self.W] += np.float32(fn(l, t))

    # schedule writers ─ each writes a time curve x layer envelope
    def write_ramp(self, l_lo, l_hi, t_lo, t_hi, g0, g1, power=1.0):
        env = gaussian_envelope(l_lo, l_hi, self.L)
        span = max(t_hi - t_lo, 1)
        for t in range(t_lo, t_hi + 1):
            g = g0 + (g1 - g0) * ((t - t_lo) / span) ** power
            self.add_column(t, env * np.float32(g))

    def write_const(self, l_lo, l_hi, t_lo, t_hi, g):
        env = gaussian_envelope(l_lo, l_hi, self.L)
        for t in range(t_lo, t_hi + 1):
            self.add_column(t, env * np.float32(g))

    def write_decay(self, l_lo, l_hi, t0, g, tau, horizon):
        env = gaussian_envelope(l_lo, l_hi, self.L)
        for t in range(t0, t0 + horizon + 1):
            self.add_column(t, env * np.float32(g * np.exp(-(t - t0) / tau)))

    def write_window(self, l_lo, l_hi, t_lo, t_hi, g, edge=2.0):
        env = gaussian_envelope(l_lo, l_hi, self.L)
        for t in range(t_lo, t_hi + 1):
            rise = 1.0 / (1.0 + np.exp(-(t - t_lo - 2) / edge))
            fall = 1.0 / (1.0 + np.exp((t - t_hi + 2) / edge))
            self.add_column(t, env * np.float32(g * rise * fall))

    # ── algebra (closed: every op returns a GainField) ───────────────
    def _check(self, other: "GainField"):
        if (self.L, self.W) != (other.L, other.W):
            raise ValueError("lattice shape mismatch")

    def __add__(self, other: "GainField") -> "GainField":
        self._check(other)
        out = GainField(self.L, self.W)
        for fi in set(self.tiles) | set(other.tiles):
            a = self.tiles.get(fi)
            b = other.tiles.get(fi)
            if a is not None and b is not None:
                out.tiles[fi] = a + b
            else:
                out.tiles[fi] = (a if a is not None else b).copy()
        return out

    def __mul__(self, alpha: float) -> "GainField":
        out = GainField(self.L, self.W)
        for fi, tile in self.tiles.items():
            out.tiles[fi] = tile * np.float32(alpha)
        return out

    __rmul__ = __mul__

    def mask(self, l_lo, l_hi, t_lo, t_hi, factor: float) -> "GainField":
        """Scale a rectangular region; identity elsewhere."""
        out = GainField(self.L, self.W)
        for fi, tile in self.tiles.items():
            nt = tile.copy()
            base = fi * self.W
            for w in range(self.W):
                t = base + w
                if t_lo <= t <= t_hi:
                    nt[l_lo : l_hi + 1, w] *= np.float32(factor)
            out.tiles[fi] = nt
        return out

    def shift_t(self, dt: int) -> "GainField":
        """Translate the field along the time axis."""
        out = GainField(self.L, self.W)
        for fi, tile in self.tiles.items():
            base = fi * self.W
            for w in range(self.W):
                col = tile[:, w]
                if not col.any():
                    continue
                t = base + w + dt
                if t >= 0:
                    out.add_column(t, col)
        return out

    def crop(self, t_lo: int, t_hi: int) -> "GainField":
        out = GainField(self.L, self.W)
        for t in range(t_lo, t_hi + 1):
            col = self.column(t)
            if col.any():
                out.add_column(t, col)
        return out

    # ── identity ─────────────────────────────────────────────────────
    def support(self) -> list[int]:
        return sorted(fi for fi, tile in self.tiles.items() if tile.any())

    def to_dict(self) -> dict:
        return {
            "layers": self.L,
            "frame": self.W,
            "tiles": {
                str(fi): np.round(tile.astype(np.float64), 7).tolist()
                for fi, tile in sorted(self.tiles.items())
                if tile.any()
            },
        }

    def hash(self) -> str:
        return chash(self.to_dict())
