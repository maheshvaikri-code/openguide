"""Controller: the per-turn reconciliation loop.

Senses behavioral state, computes drift against the contract's setpoints,
dispatches recovery, and records every turn through the Trace recorder — the
only write path.
"""
from .reconciler import ReconcileOutput, Reconciler

__all__ = ["Reconciler", "ReconcileOutput"]
