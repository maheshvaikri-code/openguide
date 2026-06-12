"""External measures: a registered Python callable or a webhook adapter.

The webhook form is declared here but kept thin — the deterministic path is a
Python callable so deployments (and tests) can wire a real scorer like the
CodeMonk CESR adapter without a network round-trip in the hot loop.
"""
from __future__ import annotations

from typing import Any, Callable

from .base import Measure


class ExternalMeasure(Measure):
    """Wraps an external scorer ``fn(ctx) -> float | None``.

    Marked deterministic by default (an external service is treated as a stable
    oracle); pass ``determinism='stochastic'`` if the source is sampled.
    """

    latency_class = "slow"

    def __init__(self, measure_id: str, fn: Callable[[dict[str, Any]], float | None],
                 *, determinism: str = "deterministic"):
        super().__init__(measure_id, determinism=determinism, latency_class="slow")
        self._fn = fn

    def _read(self, ctx: dict[str, Any]) -> float | None:
        return self._fn(ctx)
