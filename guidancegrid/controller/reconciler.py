"""Per-turn reconciler.

For each turn:
  1. read every invariant's measure  -> readings (value | gap)
  2. drift = weighted mean of soft floor violations, in [0,1]
  3. run hard structural validators (T3)
  4. evaluate state-predicate triggers
  5. dispatch recovery from the drift ladder (re_anchor | escalate | halt)
  6. assemble the T2 re-anchor text to inject next turn (the actuation)
  7. append ONE behavioral-state record to the Trace — the only write path

Determinism: given the same manifest and the same measure readings, the trace
head is bit-identical (replay key). All floats are rounded before recording.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..channels.t2_text import ReanchorAssembler
from ..channels.t3_validate import Validator
from ..compiler.compile import CompiledContract
from ..core.trace import Trace
from ..sensors.base import MeasureRegistry, Reading


@dataclass
class ReconcileOutput:
    turn: int
    drift: float
    action: str | None                 # recovery action fired this turn
    halted: bool
    reanchor_text: str | None          # T2 text to inject next turn (or None)
    state: dict[str, Any]              # the behavioral-state record appended
    validation_failures: list[str] = field(default_factory=list)
    sensor_gaps: list[str] = field(default_factory=list)


def _round(x: float) -> float:
    return round(float(x), 6)


class Reconciler:
    def __init__(self, compiled: CompiledContract, registry: MeasureRegistry,
                 manifest: dict[str, Any], trace: Trace | None = None):
        self.c = compiled
        self.registry = registry
        self.trace = trace or Trace(manifest)
        self.assembler = ReanchorAssembler(compiled)
        self.validator = Validator(compiled.t3_validators, registry)
        self.escalations = 0
        self.halted = False

    # ── drift ────────────────────────────────────────────────────────
    def _drift(self, readings: dict[str, Reading]) -> tuple[float, list[str]]:
        # drift = weighted SUM of floor violations, clipped to [0,1]. weight is
        # the invariant's "drift contribution" (OBC §3) — a healthy invariant
        # contributes 0 and never dilutes another invariant's violation.
        total = 0.0
        gaps: list[str] = []
        for spec in self.c.soft_invariants():
            if spec.floor is None or spec.floor <= 0.0:
                continue                    # no positive setpoint => not a drift source
            r = readings[spec.id]
            if r.is_gap:
                gaps.append(spec.id)
                continue
            total += spec.weight * max(0.0, spec.floor - r.value)
        return min(max(total, 0.0), 1.0), gaps

    # ── triggers (state predicates only in Phase 1) ──────────────────
    def _fired_triggers(self, readings: dict[str, Reading], drift: float) -> list[str]:
        fired: list[str] = []
        env = {spec.id: (readings[spec.id].value or 0.0) for spec in self.c.invariants}
        env["drift"] = drift
        for trig in self.c.trigger_table:
            on = str(trig.get("on", ""))
            if not on.startswith("state:"):
                continue                    # token: triggers handled by the stream layer
            ref = trig["apply"].get("ref")
            if _eval_state_pred(on[len("state:"):], env):
                if ref:
                    fired.append(ref)
        return fired

    # ── one turn ─────────────────────────────────────────────────────
    def step(self, turn: int, ctx: dict[str, Any]) -> ReconcileOutput:
        readings = {spec.id: self.registry.read(spec.measure, ctx) for spec in self.c.invariants}
        drift, drift_gaps = self._drift(readings)

        vres = self.validator.validate(ctx)
        fired_refs = self._fired_triggers(readings, drift)
        # token: triggers are detected upstream (in the stream layer) and passed in
        for r in ctx.get("token_trigger_refs", []) or []:
            if r not in fired_refs:
                fired_refs.append(r)

        # recovery dispatch: drift ladder, OR a hard validation failure forces re_anchor
        action = self.c.recovery.action_for(drift)
        if action is None and not vres.ok:
            action = "re_anchor"
        if action == "escalate":
            self.escalations += 1
        if action == "halt":
            self.halted = True

        recovery_fired = action in ("re_anchor", "escalate") or bool(fired_refs)
        active = self.c.active_signals(turn)
        # transient trigger refs join the active set for this turn's re-anchor
        active_refs = list(active.keys()) + [r for r in fired_refs if r not in active]
        reanchor_text = self.assembler.assemble(turn, active_refs, recovery_fired=recovery_fired)

        gaps = sorted(set(drift_gaps) | set(vres.gaps))
        inv_block = {}
        for spec in self.c.invariants:
            r = readings[spec.id]
            inv_block[spec.id] = {
                "reading": None if r.is_gap else _round(r.value),
                "floor": spec.floor,
                "violated": (not r.is_gap and spec.floor is not None and r.value < spec.floor),
                "determinism": r.determinism,
            }

        record = {
            "ev": "STATE",
            "turn": turn,
            "tier_active": self.c.tier_active,
            "invariants": inv_block,
            "drift": _round(drift),
            "signals_active": {k: _round(v) for k, v in active.items()},
            "recovery_fired": action,
            "validation_failures": vres.failures,
            "sensor_gaps": gaps,
            "reanchored": reanchor_text is not None,
        }
        self.trace.append(record)            # ← the only write path

        return ReconcileOutput(
            turn=turn, drift=_round(drift), action=action, halted=self.halted,
            reanchor_text=reanchor_text, state=record,
            validation_failures=vres.failures, sensor_gaps=gaps,
        )


def _eval_state_pred(expr: str, env: dict[str, float]) -> bool:
    """Evaluate a tiny predicate like 'drift>0.3' or 'context_obedience>0.40'.
    Supports one comparison operator; no arithmetic. Safe (no eval)."""
    for op in (">=", "<=", ">", "<", "=="):
        if op in expr:
            lhs, rhs = expr.split(op, 1)
            lhs = lhs.strip()
            try:
                left = float(env.get(lhs, 0.0))
                right = float(rhs.strip())
            except ValueError:
                return False
            if op == ">":
                return left > right
            if op == "<":
                return left < right
            if op == ">=":
                return left >= right
            if op == "<=":
                return left <= right
            return left == right
    return False
