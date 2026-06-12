"""OBC loading, validation, and canonical hashing."""
import copy
import os

import pytest

from guidancegrid.obc import contract_hash, validate_contract
from guidancegrid.obc.contract import ContractError, load_contract

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "spec", "obc", "examples")


def _ex(name):
    return load_contract(os.path.join(EXAMPLES, name))


EXAMPLE_FILES = ["coding-agent-default.toml", "support-tenant.toml", "browsing-injection.toml"]


# ── examples are well-formed ──────────────────────────────────────────
@pytest.mark.parametrize("fn", EXAMPLE_FILES)
def test_example_contracts_validate(fn):
    c = validate_contract(_ex(fn))
    assert c["contract"]["name"]


def test_contract_hash_is_deterministic_and_order_insensitive():
    c = _ex("coding-agent-default.toml")
    h1 = contract_hash(c)
    # reorder top-level keys: canonical encoding must absorb it
    reordered = {k: c[k] for k in reversed(list(c.keys()))}
    assert contract_hash(reordered) == h1
    assert h1.startswith("sha256:")


def test_contract_hash_is_sensitive_to_change():
    c = _ex("coding-agent-default.toml")
    h1 = contract_hash(c)
    c2 = copy.deepcopy(c)
    c2["contract"]["version"] = "0.1.1"
    assert contract_hash(c2) != h1


# ── validation rejects malformed contracts ────────────────────────────
def test_missing_contract_table():
    with pytest.raises(ContractError):
        validate_contract({"identity": {"persona": "x"}})


def test_invalid_enforcement_floor():
    with pytest.raises(ContractError):
        validate_contract({"contract": {"name": "x", "version": "0.1.0", "enforcement_floor": "t9"}})


def test_invariant_needs_floor_or_hard():
    c = {"contract": {"name": "x", "version": "0.1.0"},
         "invariants": [{"id": "a", "measure": "judge:foo"}]}
    with pytest.raises(ContractError):
        validate_contract(c)


def test_invariant_bad_measure_prefix():
    c = {"contract": {"name": "x", "version": "0.1.0"},
         "invariants": [{"id": "a", "measure": "magic:foo", "floor": 0.5}]}
    with pytest.raises(ContractError):
        validate_contract(c)


def test_duplicate_invariant_id():
    c = {"contract": {"name": "x", "version": "0.1.0"},
         "invariants": [{"id": "a", "measure": "judge:foo", "floor": 0.5},
                        {"id": "a", "measure": "judge:bar", "hard": True}]}
    with pytest.raises(ContractError):
        validate_contract(c)


def test_bad_recovery_verb():
    c = {"contract": {"name": "x", "version": "0.1.0"},
         "recovery": {"drift_threshold": 0.3, "actions": ["nuke@0.9"]}}
    with pytest.raises(ContractError):
        validate_contract(c)


def test_hard_invariant_without_floor_is_ok():
    c = {"contract": {"name": "x", "version": "0.1.0"},
         "invariants": [{"id": "a", "measure": "structural:foo", "hard": True}]}
    assert validate_contract(c)
