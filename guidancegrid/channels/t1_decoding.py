"""T1: constrained decoding for hard structural invariants on local models.

Enforces structure at the logit level — disallowed next-tokens are masked to
-inf before sampling, so an invariant like "valid JSON" or "tool name from this
set" holds *by construction* rather than being validated after the fact.

The production grammar backend is Outlines / llguidance (guarded import below);
this module also ships a dependency-light masker — `apply_logit_mask` plus a few
`Constraint` implementations — that works on numpy or torch logits and needs no
extra packages, so the T1 path is testable and usable out of the box.
"""
from __future__ import annotations

from typing import Any, Protocol

import numpy as np

NEG_INF = float("-inf")


def apply_logit_mask(logits, allowed_ids) -> Any:
    """Mask all but ``allowed_ids`` to -inf. Works on a numpy array or a torch
    tensor (1-D over the vocab). Returns the same type."""
    if allowed_ids is None:
        return logits
    allowed = set(int(i) for i in allowed_ids)
    try:  # torch path
        import torch

        if isinstance(logits, torch.Tensor):
            mask = torch.full_like(logits, NEG_INF)
            idx = torch.tensor(sorted(allowed), dtype=torch.long, device=logits.device)
            mask[idx] = logits[idx]
            return mask
    except ModuleNotFoundError:
        pass
    out = np.full_like(np.asarray(logits, dtype=np.float64), NEG_INF)
    idx = np.fromiter(allowed, dtype=np.int64)
    out[idx] = np.asarray(logits, dtype=np.float64)[idx]
    return out


class Constraint(Protocol):
    def allowed(self, prefix_ids: list[int]) -> set[int] | None:
        """Allowed next-token ids given the generated prefix; None = no limit."""
        ...


class AllowlistConstraint:
    """A fixed set of allowed token ids (state-independent)."""

    def __init__(self, allowed_ids):
        self._allowed = set(int(i) for i in allowed_ids)

    def allowed(self, prefix_ids: list[int]) -> set[int]:
        return self._allowed


class SequenceConstraint:
    """Allow only tokens that continue one of a fixed set of id sequences —
    e.g. restrict a tool name to a known vocabulary of token paths."""

    def __init__(self, sequences: list[list[int]]):
        self.sequences = [list(s) for s in sequences]

    def allowed(self, prefix_ids: list[int]) -> set[int] | None:
        nxt: set[int] = set()
        for seq in self.sequences:
            if len(prefix_ids) < len(seq) and seq[: len(prefix_ids)] == prefix_ids:
                nxt.add(seq[len(prefix_ids)])
        return nxt or None


class ConstrainedDecoder:
    """Applies a Constraint to logits during stepwise decoding."""

    def __init__(self, constraint: Constraint):
        self.constraint = constraint

    def mask_logits(self, logits, prefix_ids: list[int]):
        return apply_logit_mask(logits, self.constraint.allowed(prefix_ids))

    def next_token(self, logits, prefix_ids: list[int]) -> int:
        """Greedy argmax under the constraint (numpy or torch logits)."""
        masked = self.mask_logits(logits, prefix_ids)
        try:
            import torch

            if isinstance(masked, torch.Tensor):
                return int(torch.argmax(masked).item())
        except ModuleNotFoundError:
            pass
        return int(np.argmax(np.asarray(masked)))


def outlines_available() -> bool:
    """Whether the Outlines grammar backend is importable (production T1)."""
    try:
        import outlines  # noqa: F401

        return True
    except ModuleNotFoundError:
        return False
