"""Judge measures: LLM-as-judge over any OpenAI-compatible endpoint.

Always tagged ``stochastic`` — a judge reading must never be mistaken for a
deterministic structural check. The scoring call is injected as a callable so
the measure is testable and seedable; the production adapter is a thin wrapper
that formats a rubric prompt and parses a [0,1] score from the endpoint.
"""
from __future__ import annotations

from typing import Any, Callable

from .base import Measure


class JudgeMeasure(Measure):
    """Wraps a scoring function ``scorer(ctx) -> float | None`` (0..1).

    In production ``scorer`` calls an OpenAI-compatible endpoint with a rubric
    and parses the score; in tests it is a deterministic function.
    """

    determinism = "stochastic"
    latency_class = "slow"

    def __init__(self, measure_id: str, scorer: Callable[[dict[str, Any]], float | None],
                 *, rubric: str = ""):
        super().__init__(measure_id, determinism="stochastic", latency_class="slow")
        self._scorer = scorer
        self.rubric = rubric

    def _read(self, ctx: dict[str, Any]) -> float | None:
        return self._scorer(ctx)
