"""Enforcement channels: the actuators a compiled contract drives.

t2_text  - scheduled re-anchoring (contract fragments at frame boundaries)
t3_validate - structural validators + retry policy

t0 (activation) and t1 (decoding) land in Phase 4.
"""
from .t2_text import ReanchorAssembler
from .t3_validate import ValidationResult, Validator

__all__ = ["ReanchorAssembler", "Validator", "ValidationResult"]
