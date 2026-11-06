"""Grid = {signal -> GainField}, the Spec that compiles to it, and the
SignalPack holding the actual steering vectors.

Spec     : declarative program (small, hand-written, hashed)
Grid     : compiled gain fields (the literal grid)
SignalPack: per-model vectors, content-addressed, referenced by hash only
"""
from __future__ import annotations

import numpy as np

from .canonical import bhash, chash
from .field import GainField


class Grid:
    def __init__(self, layers: int = 32, frame: int = 16):
        self.L = layers
        self.W = frame
        self.fields: dict[str, GainField] = {}

    def field(self, name: str) -> GainField:
        if name not in self.fields:
            self.fields[name] = GainField(self.L, self.W)
        return self.fields[name]

    def column(self, t: int) -> dict[str, np.ndarray]:
        """All signal gain columns at step t (sparse: zero columns omitted)."""
        out = {}
        for name, f in self.fields.items():
            col = f.column(t)
            if col.any():
                out[name] = col
        return out

    def total_column(self, t: int) -> np.ndarray:
        tot = np.zeros(self.L, dtype=np.float32)
        for col in self.column(t).values():
            tot += col
        return tot

    def compose(self, other: "Grid", alpha: float = 1.0) -> "Grid":
        """G3 = G1 (+) alpha*G2 — same-named signals add cellwise."""
        if (self.L, self.W) != (other.L, other.W):
            raise ValueError("lattice shape mismatch")
        out = Grid(self.L, self.W)
        for name in set(self.fields) | set(other.fields):
            a = self.fields.get(name)
            b = other.fields.get(name)
            if a is not None and b is not None:
                out.fields[name] = a + (b * alpha)
            elif a is not None:
                out.fields[name] = a * 1.0
            else:
                out.fields[name] = b * alpha
        return out

    def hash(self) -> str:
        return chash({n: f.to_dict() for n, f in sorted(self.fields.items())})


# ── spec ──────────────────────────────────────────────────────────────

def spec_hash(spec: dict) -> str:
    return chash(spec)


def compile_spec(spec: dict) -> Grid:
    """Spec -> Grid. Static schedules only; triggers stay dynamic (runtime)."""
    grid = Grid(layers=spec.get("layers", 32), frame=spec.get("frame", 16))
    for name, s in spec.get("signals", {}).items():
        f = grid.field(name)
        l_lo, l_hi = s["layers"]
        sch = s["schedule"]
        kind = sch["type"]
        if kind == "ramp":
            f.write_ramp(l_lo, l_hi, sch["t"][0], sch["t"][1], sch["g"][0], sch["g"][1],
                         sch.get("power", 1.0))
        elif kind == "const":
            f.write_const(l_lo, l_hi, sch["t"][0], sch["t"][1], sch["g"])
        elif kind == "window":
            f.write_window(l_lo, l_hi, sch["t"][0], sch["t"][1], sch["g"])
        elif kind == "decay":
            f.write_decay(l_lo, l_hi, sch["t0"], sch["g"], sch["tau"], sch.get("horizon", 64))
        elif kind == "none":
            pass  # trigger-only signal: field starts empty
        else:
            raise ValueError(f"unknown schedule type: {kind}")
    return grid


# ── signal pack ───────────────────────────────────────────────────────

# The one steering signal a pack holds and the gain field drives (numpy-only: naming it needs no torch).
STEER_SIGNAL = "anchor"


class SignalPack:
    """Per-model steering vectors: {signal -> {layer -> vector(d)}}."""

    def __init__(self, model_id: str, d: int):
        self.model_id = model_id
        self.d = d
        self.vectors: dict[str, dict[int, np.ndarray]] = {}

    def derive_contrast(self, name: str, pos: np.ndarray, neg: np.ndarray, layers: range):
        """Toy contrast-pair derivation: unit(mean(pos) - mean(neg)) per layer.
        pos/neg: (n_examples, L, d) activation stacks."""
        sig = {}
        for l in layers:
            v = pos[:, l, :].mean(axis=0) - neg[:, l, :].mean(axis=0)
            n = np.linalg.norm(v)
            sig[l] = (v / n if n > 1e-9 else v).astype(np.float32)
        self.vectors[name] = sig

    def set_vector(self, name: str, layer: int, v: np.ndarray):
        self.vectors.setdefault(name, {})[layer] = v.astype(np.float32)

    def get(self, name: str, layer: int) -> np.ndarray | None:
        return self.vectors.get(name, {}).get(layer)

    def hash(self) -> str:
        h = bytearray()
        for name in sorted(self.vectors):
            for layer in sorted(self.vectors[name]):
                h += name.encode() + b"|" + str(layer).encode() + b"|"
                h += np.ascontiguousarray(self.vectors[name][layer], dtype=np.float32).tobytes()
        return bhash(bytes(h) + self.model_id.encode())

    def save(self, path: str):
        arrays = {
            f"{name}__{layer}": vec
            for name, sig in self.vectors.items()
            for layer, vec in sig.items()
        }
        np.savez(path, __model_id__=np.array(self.model_id), **arrays)

    @classmethod
    def load(cls, path: str) -> "SignalPack":
        data = np.load(path, allow_pickle=False)
        model_id = str(data["__model_id__"])
        names = [k for k in data.files if k != "__model_id__"]
        d = int(data[names[0]].shape[0]) if names else 0
        pack = cls(model_id, d)
        for key in names:
            name, layer = key.rsplit("__", 1)
            pack.set_vector(name, int(layer), data[key])
        return pack

    # ── safetensors (the production pack format) ─────────────────────
    def save_safetensors(self, path: str) -> str:
        """Write a content-addressable .safetensors pack; returns its hash.
        model_id and pack_hash are stored in the file metadata."""
        from safetensors.numpy import save_file

        tensors = {
            f"{name}__{layer}": np.ascontiguousarray(vec, dtype=np.float32)
            for name, sig in self.vectors.items()
            for layer, vec in sig.items()
        }
        save_file(tensors, path, metadata={"model_id": self.model_id, "pack_hash": self.hash()})
        return self.hash()

    @classmethod
    def load_safetensors(cls, path: str) -> "SignalPack":
        from safetensors import safe_open

        with safe_open(path, framework="numpy") as f:
            meta = f.metadata() or {}
            keys = list(f.keys())
            d = int(f.get_tensor(keys[0]).shape[0]) if keys else 0
            pack = cls(meta.get("model_id", "unknown"), d)
            for key in keys:
                name, layer = key.rsplit("__", 1)
                pack.set_vector(name, int(layer), f.get_tensor(key))
        return pack
