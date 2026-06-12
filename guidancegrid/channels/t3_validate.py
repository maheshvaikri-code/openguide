"""T3: structural validation + retry policy.

Hard, deterministic invariants that must hold on a turn's output. A failed
validation returns a result the controller can act on (retry the turn, or
escalate). This is the universal tier — it works on any model because it only
reads outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..compiler.compile import InvariantSpec
from ..sensors.base import MeasureRegistry


@dataclass
class ValidationResult:
    ok: bool
    failures: list[str] = field(default_factory=list)   # invariant ids that failed
    gaps: list[str] = field(default_factory=list)        # invariants with no sensor


class Validator:
    """Runs a compiled contract's hard structural invariants against a turn.

    A structural invariant passes when its measure reads >= 0.5 (bool 1.0/0.0,
    or a graded score). A missing sensor is a *gap*, not a pass — recorded, and
    treated as non-blocking so the data plane never stalls on the control plane.
    """

    def __init__(self, validators: list[InvariantSpec], registry: MeasureRegistry,
                 max_retries: int = 1):
        self.validators = validators
        self.registry = registry
        self.max_retries = max_retries

    def validate(self, ctx: dict[str, Any]) -> ValidationResult:
        failures: list[str] = []
        gaps: list[str] = []
        for spec in self.validators:
            reading = self.registry.read(spec.measure, ctx)
            if reading.is_gap:
                gaps.append(spec.id)
                continue
            if reading.value < 0.5:
                failures.append(spec.id)
        return ValidationResult(ok=not failures, failures=failures, gaps=gaps)

    def should_retry(self, attempt: int, result: ValidationResult) -> bool:
        return (not result.ok) and attempt < self.max_retries
