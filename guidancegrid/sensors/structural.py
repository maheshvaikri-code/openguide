"""Structural measures: deterministic checks (schema, regex, file-scope, fn)."""
from __future__ import annotations

import re
from typing import Any, Callable

from .base import Measure


class StructuralMeasure(Measure):
    """Wraps a deterministic predicate ``fn(ctx) -> bool | float``."""

    determinism = "deterministic"
    latency_class = "fast"

    def __init__(self, measure_id: str, fn: Callable[[dict[str, Any]], bool | float | None]):
        super().__init__(measure_id)
        self._fn = fn

    def _read(self, ctx: dict[str, Any]) -> bool | float | None:
        return self._fn(ctx)

    # ── common structural constructors ───────────────────────────────
    @classmethod
    def regex_absent(cls, measure_id: str, pattern: str, key: str = "output") -> "StructuralMeasure":
        """1.0 when the pattern does NOT appear in ctx[key] (e.g. a forbidden token)."""
        rx = re.compile(pattern)
        return cls(measure_id, lambda ctx: rx.search(str(ctx.get(key, ""))) is None)

    @classmethod
    def regex_present(cls, measure_id: str, pattern: str, key: str = "output") -> "StructuralMeasure":
        rx = re.compile(pattern)
        return cls(measure_id, lambda ctx: rx.search(str(ctx.get(key, ""))) is not None)

    @classmethod
    def flag(cls, measure_id: str, key: str) -> "StructuralMeasure":
        """Reads a boolean/numeric flag the harness places on the context."""
        return cls(measure_id, lambda ctx: ctx.get(key))
