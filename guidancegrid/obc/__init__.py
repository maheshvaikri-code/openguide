"""Open Behavioral Contract (OBC): loading, validation, hashing.

Phase 0 ships the schema + canonical contract hashing. The tier compiler
(OBC -> {T2 fragments, T3 validators, ProbeSpec, TriggerTable}) lands in
Phase 1 under guidancegrid/compiler/.
"""
from .contract import contract_hash, load_contract, validate_contract

__all__ = ["load_contract", "contract_hash", "validate_contract"]
