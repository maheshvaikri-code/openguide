"""Capability resolution: pick the strongest enforcement tier a target allows.

Each target model exposes a CapabilityDescriptor declaring which tiers it
supports. The resolver picks the strongest tier the model supports, subject to
the contract's ``enforcement_floor`` (the minimum it will accept). If the model
cannot meet the floor, resolution raises — the runtime refuses to run rather
than silently degrading enforcement.

Tier order (strongest first): t0 > t1 > t2 > t3.
  t0 activation steering · t1 constrained decoding · t2 re-anchoring · t3 validation
"""
from __future__ import annotations

from dataclasses import dataclass, field

# strongest -> weakest; index = strength rank
TIER_ORDER = ["t0", "t1", "t2", "t3"]


def tier_rank(tier: str) -> int:
    """Lower rank = stronger tier. t0 -> 0, t3 -> 3."""
    return TIER_ORDER.index(tier)


class CapabilityError(RuntimeError):
    """Raised when no supported tier can satisfy the enforcement floor."""


@dataclass(frozen=True)
class CapabilityDescriptor:
    """What a target model lets the runtime do."""

    model_id: str
    tiers: frozenset[str]          # supported tiers, e.g. {"t2", "t3"}
    notes: str = ""

    def supports(self, tier: str) -> bool:
        return tier in self.tiers

    def strongest(self) -> str:
        """The strongest supported tier."""
        return min(self.tiers, key=tier_rank)


# Static capability registry for known targets (blueprint §2 Phase 1).
# Closed APIs cap out at t2 (text re-anchoring); open-weight servers can do t0/t1.
def _d(model_id: str, tiers, notes: str = "") -> CapabilityDescriptor:
    return CapabilityDescriptor(model_id=model_id, tiers=frozenset(tiers), notes=notes)


CAPABILITIES: dict[str, CapabilityDescriptor] = {
    # closed APIs: prompt-level only
    "openai:*": _d("openai:*", {"t2", "t3"}, "closed API; text re-anchor + structural"),
    "anthropic:*": _d("anthropic:*", {"t2", "t3"}, "closed API; text re-anchor + structural"),
    "google:*": _d("google:*", {"t2", "t3"}, "closed API; text re-anchor + structural"),
    # local / open-weight servers: full stack
    "vllm:*": _d("vllm:*", {"t0", "t1", "t2", "t3"}, "open weights; activation + decoding"),
    "llamacpp:*": _d("llamacpp:*", {"t1", "t2", "t3"}, "grammar decoding + re-anchor"),
    "hf:*": _d("hf:*", {"t0", "t1", "t2", "t3"}, "HF transformers; full stack"),
    # the test/mock target: text tier only (deterministic)
    "mock:*": _d("mock:*", {"t2", "t3"}, "scripted mock LLM for tests"),
}

# default when a provider is unknown: assume closed-API-equivalent (t2/t3).
DEFAULT_DESCRIPTOR = _d("unknown:*", {"t2", "t3"}, "unknown target; assume closed-API tiers")


@dataclass
class CapabilityResolver:
    """Resolves model_id -> descriptor -> active tier for a contract."""

    registry: dict[str, CapabilityDescriptor] = field(default_factory=lambda: dict(CAPABILITIES))

    def descriptor_for(self, model_id: str) -> CapabilityDescriptor:
        if model_id in self.registry:
            return self.registry[model_id]
        provider = model_id.split(":", 1)[0] if ":" in model_id else model_id
        wild = f"{provider}:*"
        return self.registry.get(wild, DEFAULT_DESCRIPTOR)

    def resolve(self, model_id: str, enforcement_floor: str = "t3") -> str:
        """Return the strongest supported tier that is at least as strong as
        ``enforcement_floor``. Raise CapabilityError if the floor is unmet."""
        desc = self.descriptor_for(model_id)
        floor_rank = tier_rank(enforcement_floor)
        # candidate tiers the model supports that meet-or-exceed the floor
        eligible = [t for t in desc.tiers if tier_rank(t) <= floor_rank]
        if not eligible:
            raise CapabilityError(
                f"{model_id!r} supports {sorted(desc.tiers)} but contract requires "
                f"at least {enforcement_floor!r}; refusing to run."
            )
        return min(eligible, key=tier_rank)
