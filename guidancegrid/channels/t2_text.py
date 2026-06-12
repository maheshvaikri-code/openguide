"""T2: scheduled re-anchoring.

Assembles contract fragments to inject at frame boundaries (every N turns) and
whenever recovery fires. Budget-aware: the assembled text is capped so the
re-anchor never crowds out the actual task context.

The assembler is pure — given (turn, active signals, recovery?) it returns the
text to inject, or None. The harness owns *where* the text goes (system message,
prefix); the reconciler records *that* it was injected.
"""
from __future__ import annotations

from ..compiler.compile import CompiledContract


class ReanchorAssembler:
    def __init__(self, compiled: CompiledContract):
        self.c = compiled
        self.every = int(compiled.reanchor_plan.get("every", 8))
        self.on_recovery = bool(compiled.reanchor_plan.get("on_recovery", True))
        self.budget = int(compiled.reanchor_plan.get("budget_chars", 600))

    def due(self, turn: int, recovery_fired: bool) -> bool:
        if recovery_fired and self.on_recovery:
            return True
        return turn > 0 and self.every > 0 and turn % self.every == 0

    def assemble(self, turn: int, active_signals: list[str], recovery_fired: bool) -> str | None:
        """Return re-anchor text to inject this turn, or None if not due."""
        if self.c.tier_active not in ("t2",) and self.c.tier_active not in ("t3",):
            # t0/t1 carry enforcement structurally; text re-anchor still allowed
            # but only emitted for t2. (t3 = validation only, no injection.)
            pass
        if self.c.tier_active == "t3":
            return None                      # validation-only tier never injects
        if not self.due(turn, recovery_fired):
            return None
        refs = active_signals or list(self.c.t2_fragments.keys())
        parts: list[str] = []
        if recovery_fired:
            parts.append("[re-anchor] Re-aligning to the active contract.")
        for ref in refs:
            frag = self.c.t2_fragments.get(ref)
            if frag:
                parts.append(frag)
        if not parts:
            return None
        text = "\n".join(parts)
        if len(text) > self.budget:
            text = text[: self.budget].rstrip() + " …"
        return text
