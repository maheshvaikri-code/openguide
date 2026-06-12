"""GuidanceGrid: a literal control grid over (layer x step).

Reference runtime for the OpenGuide control plane. Total, frame-tiled,
algebraic, hash-addressed, learnable. numpy only.

Layout:
  core/       - canonical encoding, GainField, Grid/SignalPack, GridRuntime, Trace
  tune/       - grid tuning (toy analytic plant; real-model tuning is Phase 4)
  obc/        - Open Behavioral Contract schema + loader
  compiler/   - OBC -> tier artifacts (capability resolver + compiler)
  sensors/    - typed measures (structural/external/judge)
  channels/   - enforcement actuators (t2 re-anchor, t3 validate)
  controller/ - per-turn reconciler
  store/      - CAS + fleet index
"""
from .channels import ReanchorAssembler, Validator
from .compiler import (
    CapabilityResolver,
    CompiledContract,
    compile_contract,
)
from .controller import Reconciler
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
from .obc import contract_hash, load_contract, validate_contract
from .sensors import (
    ExternalMeasure,
    JudgeMeasure,
    MeasureRegistry,
    StructuralMeasure,
)
from .store import RunRecord, Store
from .tune import constant_baseline, default_drift, grid_tune, simulate

__version__ = "0.1.0"
__all__ = [
    # core
    "GainField", "Grid", "SignalPack", "GridRuntime", "Trace",
    "compile_spec", "spec_hash", "inject", "gaussian_envelope",
    "canonical_json", "chash", "bhash",
    # tune
    "grid_tune", "constant_baseline", "simulate", "default_drift",
    # obc + compiler
    "load_contract", "validate_contract", "contract_hash",
    "CapabilityResolver", "CompiledContract", "compile_contract",
    # sensors + channels + controller + store
    "MeasureRegistry", "StructuralMeasure", "ExternalMeasure", "JudgeMeasure",
    "ReanchorAssembler", "Validator", "Reconciler",
    "Store", "RunRecord",
]
