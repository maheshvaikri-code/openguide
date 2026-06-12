"""OBC -> CompiledContract.

Resolves the active tier for a target model, then lowers the declarative
contract into the artifacts the runtime executes:

  - invariants     : resolved InvariantSpec list (id, measure ref, floor, weight, hard)
  - t2_fragments   : signal ref -> re-anchor text (the contract made injectable)
  - reanchor_plan  : when to re-anchor (every N turns + on recovery)
  - t3_validators  : structural invariants that must hold (hard, tier 1/3)
  - probe_specs    : probe: invariants deferred to tier 0 (Phase 4)
  - trigger_table  : event predicate -> signal application
  - recovery       : drift threshold + escalation ladder

The compiled contract carries the source ``contract_hash`` so every downstream
record is traceable to an exact contract version.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..obc.contract import contract_hash, validate_contract
from .capability import CapabilityResolver


@dataclass(frozen=True)
class InvariantSpec:
    id: str
    measure: str                   # OBC measure ref, e.g. "judge:adherence"
    floor: float | None
    weight: float
    hard: bool

    @property
    def kind(self) -> str:
        return self.measure.split(":", 1)[0]


@dataclass
class RecoveryPlan:
    drift_threshold: float
    # ordered ladder: (action, gate_drift). gate None => fires at drift_threshold.
    ladder: list[tuple[str, float | None]] = field(default_factory=list)

    def action_for(self, drift: float) -> str | None:
        """Highest-severity action whose gate the drift has crossed, else None."""
        chosen = None
        for action, gate in self.ladder:
            g = self.drift_threshold if gate is None else gate
            if drift >= g:
                chosen = action
        return chosen


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    t_lo: int
    t_hi: int                       # -1 => open-ended (to end of run)
    signals: list[tuple[str, Any]]  # (ref, gain-or-schedule)

    def contains(self, turn: int) -> bool:
        return turn >= self.t_lo and (self.t_hi < 0 or turn <= self.t_hi)


def _resolve_gain(gain: Any, turn: int, phase: PhaseSpec) -> float:
    """Resolve a scalar or {ramp:[a,b]} gain to a number at this turn."""
    if isinstance(gain, dict) and "ramp" in gain:
        a, b = gain["ramp"]
        span = max((phase.t_hi if phase.t_hi >= 0 else phase.t_lo + 1) - phase.t_lo, 1)
        frac = min(max((turn - phase.t_lo) / span, 0.0), 1.0)
        return float(a) + (float(b) - float(a)) * frac
    return float(gain) if gain is not None else 0.0


@dataclass
class CompiledContract:
    name: str
    version: str
    contract_hash: str
    model_id: str
    tier_active: str
    enforcement_floor: str
    invariants: list[InvariantSpec]
    phases: list[PhaseSpec]
    t2_fragments: dict[str, str]
    reanchor_plan: dict[str, Any]
    t3_validators: list[InvariantSpec]
    probe_specs: list[InvariantSpec]
    trigger_table: list[dict[str, Any]]
    recovery: RecoveryPlan
    identity: dict[str, Any]

    def hard_invariants(self) -> list[InvariantSpec]:
        return [i for i in self.invariants if i.hard]

    def soft_invariants(self) -> list[InvariantSpec]:
        return [i for i in self.invariants if not i.hard]

    def active_signals(self, turn: int) -> dict[str, float]:
        """Resolved {signal_ref -> gain} active at this turn across all phases."""
        out: dict[str, float] = {}
        for ph in self.phases:
            if ph.contains(turn):
                for ref, gain in ph.signals:
                    out[ref] = round(out.get(ref, 0.0) + _resolve_gain(gain, turn, ph), 6)
        return out


def _parse_ladder(actions: list[str]) -> list[tuple[str, float | None]]:
    out: list[tuple[str, float | None]] = []
    for a in actions:
        if "@" in a:
            verb, gate = a.split("@", 1)
            out.append((verb, float(gate)))
        else:
            out.append((a, None))
    return out


def _fragment_for(signal_ref: str, signals: dict[str, Any], identity: dict[str, Any]) -> str:
    """Assemble the re-anchor text for a signal. Uses the signal's declared
    t2_template name as a heading hook and folds in identity boundaries so the
    re-anchor always restates the contract's spine."""
    persona = identity.get("persona", "")
    boundaries = identity.get("boundaries", [])
    lines = [f"[contract:{signal_ref}]"]
    if persona:
        lines.append(f"Persona: {persona}.")
    if boundaries:
        lines.append("Boundaries: " + "; ".join(boundaries) + ".")
    return " ".join(lines)


def compile_contract(contract: dict[str, Any], model_id: str,
                     resolver: CapabilityResolver | None = None,
                     reanchor_every: int = 8) -> CompiledContract:
    """Validate + lower an OBC contract for a specific target model."""
    contract = validate_contract(contract)
    resolver = resolver or CapabilityResolver()
    floor = contract["contract"].get("enforcement_floor", "t3")
    tier = resolver.resolve(model_id, floor)

    identity = contract.get("identity", {})
    signals = contract.get("signals", {})

    phases: list[PhaseSpec] = []
    for ph in contract.get("phases", []):
        turns = ph["window"]["turns"]
        sigs = [(s["ref"], s.get("gain")) for s in ph.get("signals", [])]
        phases.append(PhaseSpec(name=ph["name"], t_lo=int(turns[0]), t_hi=int(turns[1]), signals=sigs))

    invariants: list[InvariantSpec] = []
    t3_validators: list[InvariantSpec] = []
    probe_specs: list[InvariantSpec] = []
    for inv in contract.get("invariants", []):
        spec = InvariantSpec(
            id=inv["id"],
            measure=inv["measure"],
            floor=inv.get("floor"),
            weight=float(inv.get("weight", 1.0)),
            hard=bool(inv.get("hard", False)),
        )
        invariants.append(spec)
        if spec.kind == "structural" and spec.hard:
            t3_validators.append(spec)
        if spec.kind == "probe":
            probe_specs.append(spec)

    # T2 fragments: one per signal that has any re-anchor surface.
    t2_fragments: dict[str, str] = {}
    for ref in signals:
        t2_fragments[ref] = _fragment_for(ref, signals, identity)

    rec = contract.get("recovery", {})
    recovery = RecoveryPlan(
        drift_threshold=float(rec.get("drift_threshold", 1.0)),
        ladder=_parse_ladder(rec.get("actions", [])),
    )

    reanchor_plan = {
        "every": reanchor_every,            # cadence in turns (frame-boundary inject)
        "on_recovery": True,                # always re-anchor when recovery fires
        "budget_chars": 600,                # cap re-anchor text per turn
    }

    return CompiledContract(
        name=contract["contract"]["name"],
        version=contract["contract"]["version"],
        contract_hash=contract_hash(contract),
        model_id=model_id,
        tier_active=tier,
        enforcement_floor=floor,
        invariants=invariants,
        phases=phases,
        t2_fragments=t2_fragments,
        reanchor_plan=reanchor_plan,
        t3_validators=t3_validators,
        probe_specs=probe_specs,
        trigger_table=list(contract.get("triggers", [])),
        recovery=recovery,
        identity=identity,
    )
