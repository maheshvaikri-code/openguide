"""GuidanceGrid: a literal control grid over (layer x step).

Total, frame-tiled, algebraic, hash-addressed, learnable.
Reference implementation — numpy only.
"""
from .canonical import canonical_json, chash, bhash
from .field import GainField, gaussian_envelope
from .grid import Grid, SignalPack, compile_spec, spec_hash
from .runtime import GridRuntime, inject
from .trace import Trace
from .tune import grid_tune, constant_baseline, simulate

__version__ = "0.1.0"
__all__ = [
    "GainField", "Grid", "SignalPack", "GridRuntime", "Trace",
    "compile_spec", "spec_hash", "inject", "gaussian_envelope",
    "grid_tune", "constant_baseline", "simulate",
    "canonical_json", "chash", "bhash",
]
