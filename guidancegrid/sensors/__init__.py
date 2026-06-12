"""Sensors: typed measures that read behavioral state each turn.

Every measure declares its ``determinism`` (deterministic|stochastic) and a
``latency_class`` (fast|slow). A judge-based measure must never silently
substitute for a structural one — the type is carried through to the trace.
"""
from .base import Measure, MeasureRegistry, Reading
from .external import ExternalMeasure
from .judge import JudgeMeasure
from .structural import StructuralMeasure

__all__ = [
    "Measure",
    "Reading",
    "MeasureRegistry",
    "StructuralMeasure",
    "ExternalMeasure",
    "JudgeMeasure",
]
