"""GuidanceGrid: a literal control grid over (layer x step).

Reference runtime for the OpenGuide control plane. Total, frame-tiled,
algebraic, hash-addressed, learnable. numpy only.

Layout:
  core/  - canonical encoding, GainField, Grid/SignalPack, GridRuntime, Trace
  tune/  - grid tuning (toy analytic plant; real-model tuning is Phase 4)
  obc/   - Open Behavioral Contract schema + loader (Phase 0/1)
"""
from .core import (
    GainField,
    Grid,
    GridRuntime,
    SignalPack,
    Trace,
    bhash,
    canonical_json,
    chash,
    compile_spec,
    gaussian_envelope,
    inject,
    spec_hash,
)
from .tune import constant_baseline, default_drift, grid_tune, simulate

__version__ = "0.1.0"
__all__ = [
    "GainField", "Grid", "SignalPack", "GridRuntime", "Trace",
    "compile_spec", "spec_hash", "inject", "gaussian_envelope",
    "grid_tune", "constant_baseline", "simulate", "default_drift",
    "canonical_json", "chash", "bhash",
]
