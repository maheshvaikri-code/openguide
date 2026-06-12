"""OBC loading, validation, and canonical hashing.

A contract is authored in TOML (see spec/obc/), loaded to a plain dict, and
content-addressed with the *same* canonical encoding the trace plane uses:

    contract_hash = sha256(canonical(contract))

so a contract identity is reproducible across languages. Validation here is a
focused structural check against the normative OBC v0.1 fields; when the
``jsonschema`` package is available it is additionally validated against the
published JSON Schema for full coverage.
"""
from __future__ import annotations

import os
from typing import Any

from ..core.canonical import chash

try:  # py311+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - exercised on <3.11
    import tomli as _toml  # type: ignore

_SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "spec", "obc", "obc-v0.1.schema.json"
)

VALID_ENFORCEMENT = {"t0", "t1", "t2", "t3"}
VALID_MEASURE_PREFIXES = ("judge:", "probe:", "structural:", "external:")
VALID_RECOVERY_VERBS = {"re_anchor", "escalate", "halt"}


class ContractError(ValueError):
    """Raised when a contract violates the OBC v0.1 schema."""


def load_contract(path: str) -> dict[str, Any]:
    """Load a TOML contract file into a plain dict (no validation)."""
    with open(path, "rb") as fh:
        return _toml.load(fh)


def contract_hash(contract: dict[str, Any]) -> str:
    """Canonical content hash of a contract (`sha256:...`)."""
    return chash(contract)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ContractError(msg)


def validate_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Validate a loaded contract. Returns it unchanged on success; raises
    ContractError on the first violation. Performs the normative structural
    checks, then defers to jsonschema if that package is installed."""
    c = contract.get("contract")
    _require(isinstance(c, dict), "missing [contract] table")
    _require(bool(c.get("name")), "[contract].name is required")
    _require(bool(c.get("version")), "[contract].version is required")
    floor = c.get("enforcement_floor", "t3")
    _require(
        floor in VALID_ENFORCEMENT,
        f"[contract].enforcement_floor must be one of {sorted(VALID_ENFORCEMENT)}, got {floor!r}",
    )

    invariants = contract.get("invariants", [])
    _require(isinstance(invariants, list), "[[invariants]] must be an array of tables")
    seen_ids: set[str] = set()
    for inv in invariants:
        iid = inv.get("id")
        _require(bool(iid), "each invariant needs an id")
        _require(iid not in seen_ids, f"duplicate invariant id: {iid!r}")
        seen_ids.add(iid)
        measure = inv.get("measure", "")
        _require(
            measure.startswith(VALID_MEASURE_PREFIXES),
            f"invariant {iid!r}: measure must start with one of {VALID_MEASURE_PREFIXES}, got {measure!r}",
        )
        if "floor" in inv:
            _require(0.0 <= float(inv["floor"]) <= 1.0, f"invariant {iid!r}: floor out of [0,1]")
        _require(
            ("floor" in inv) or inv.get("hard") is True,
            f"invariant {iid!r}: needs either a floor or hard=true",
        )

    for ph in contract.get("phases", []):
        _require(bool(ph.get("name")), "each phase needs a name")
        win = ph.get("window", {})
        _require("turns" in win, f"phase {ph.get('name')!r}: window.turns is required")
        turns = win["turns"]
        _require(
            isinstance(turns, list) and len(turns) == 2,
            f"phase {ph.get('name')!r}: window.turns must be [start, end]",
        )

    rec = contract.get("recovery")
    if rec is not None:
        if "drift_threshold" in rec:
            _require(0.0 <= float(rec["drift_threshold"]) <= 1.0, "recovery.drift_threshold out of [0,1]")
        for action in rec.get("actions", []):
            verb = action.split("@", 1)[0]
            _require(
                verb in VALID_RECOVERY_VERBS,
                f"recovery action {action!r}: verb must be one of {sorted(VALID_RECOVERY_VERBS)}",
            )

    _jsonschema_validate(contract)
    return contract


def _jsonschema_validate(contract: dict[str, Any]) -> None:
    """Optional full validation against the published JSON Schema."""
    try:
        import json

        import jsonschema  # type: ignore
    except ModuleNotFoundError:
        return
    if not os.path.exists(_SCHEMA_PATH):
        return
    with open(_SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    try:
        jsonschema.validate(contract, schema)
    except jsonschema.ValidationError as exc:  # pragma: no cover - thin adapter
        raise ContractError(f"jsonschema: {exc.message}") from exc
