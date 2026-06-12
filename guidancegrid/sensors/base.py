"""Measure base types and the registry that resolves OBC measure refs.

A measure reading is a value in [0,1] or None (a *sensor gap* — the data plane
must proceed on stale gains and record the gap, never block; blueprint §7.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DETERMINISM = ("deterministic", "stochastic")
LATENCY = ("fast", "slow")


@dataclass(frozen=True)
class Reading:
    """One measure reading for one turn."""

    measure_id: str
    value: float | None            # [0,1], or None for a sensor gap
    determinism: str
    latency_class: str

    @property
    def is_gap(self) -> bool:
        return self.value is None


class Measure:
    """Base measure. Subclasses implement ``_read``; ``read`` wraps it,
    clamps to [0,1], and converts failures/timeouts into a sensor gap."""

    determinism: str = "deterministic"
    latency_class: str = "fast"

    def __init__(self, measure_id: str, *, determinism: str | None = None,
                 latency_class: str | None = None):
        self.measure_id = measure_id
        if determinism is not None:
            assert determinism in DETERMINISM, determinism
            self.determinism = determinism
        if latency_class is not None:
            assert latency_class in LATENCY, latency_class
            self.latency_class = latency_class

    def _read(self, ctx: dict[str, Any]) -> float | bool | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def read(self, ctx: dict[str, Any]) -> Reading:
        try:
            raw = self._read(ctx)
        except Exception:
            raw = None                 # sensor failure => gap, never raise into the loop
        if raw is None:
            value = None
        else:
            value = 1.0 if raw is True else 0.0 if raw is False else float(raw)
            value = max(0.0, min(1.0, value))
        return Reading(self.measure_id, value, self.determinism, self.latency_class)


class MeasureRegistry:
    """Maps an OBC measure ref (e.g. ``judge:adherence``) to a Measure.

    Unregistered refs read as a sensor gap, so a contract referencing a measure
    the deployment hasn't wired up degrades safely (and visibly) rather than
    crashing.
    """

    def __init__(self) -> None:
        self._measures: dict[str, Measure] = {}

    def register(self, measure: Measure) -> Measure:
        self._measures[measure.measure_id] = measure
        return measure

    def get(self, ref: str) -> Measure | None:
        return self._measures.get(ref)

    def read(self, ref: str, ctx: dict[str, Any]) -> Reading:
        m = self._measures.get(ref)
        if m is None:
            # unknown measure: a gap, tagged by the ref's declared kind
            kind = ref.split(":", 1)[0]
            det = "stochastic" if kind == "judge" else "deterministic"
            return Reading(ref, None, det, "fast")
        return m.read(ctx)
