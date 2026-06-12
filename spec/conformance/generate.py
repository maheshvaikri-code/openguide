"""Generate golden conformance vectors from the reference implementation.

Run from repo root:  python spec/conformance/generate.py

Emits, under spec/conformance/vectors/:
  canonical/*.json   — {name, input, canonical, hash}  (10 vectors)
  chain/*.json       — {name, manifest, records, head, valid}  (valid + tampered)
  contracts.json     — {file -> contract_hash} for the 3 example contracts

The independent runner (run_conformance.py) re-derives all of these from the
spec rules ALONE — never importing guidancegrid — and must match byte-for-byte.
That mismatch-or-match is the Phase 0 gate.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)  # repo root holds the guidancegrid package

from guidancegrid.core.canonical import canonical_json, chash  # noqa: E402
from guidancegrid.core.trace import Trace  # noqa: E402
from guidancegrid.obc import contract_hash, load_contract, validate_contract  # noqa: E402

VEC = os.path.join(HERE, "vectors")


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ── canonical-encoding vectors ──────────────────────────────────────────
CANONICAL_INPUTS = {
    "01_atoms": {"b": True, "n": None, "i": 42, "s": "hello"},
    "02_key_sort": {"z": 1, "a": 2, "m": 3, "A": 4},
    "03_nested": {"outer": {"b": [3, 2, 1], "a": {"k": "v"}}},
    "04_float_9sig": {"pi": 3.14159265358979, "tiny": 0.000123456789123},
    "05_float_round": {"x": 1.0000000004, "y": 1.0000000006},
    "06_negatives": {"a": -0.5, "b": -42, "c": [-1.5, -2.5]},
    "07_unicode": {"name": "café", "emoji": "✓", "jp": "日本語"},
    "08_array_order": [3, 1, 2, {"b": 1, "a": 2}],
    "09_int_vs_float": {"i": 1, "f": 1.5, "z": 0.0},
    "10_empty": {"obj": {}, "arr": [], "s": ""},
}


def gen_canonical():
    for name, obj in CANONICAL_INPUTS.items():
        _write(
            os.path.join(VEC, "canonical", f"{name}.json"),
            {"name": name, "input": obj, "canonical": canonical_json(obj), "hash": chash(obj)},
        )
    print(f"  canonical: {len(CANONICAL_INPUTS)} vectors")


# ── chain-verification vectors ──────────────────────────────────────────
def _sample_trace():
    manifest = {"model": "toy", "spec_hash": "sha256:" + "0" * 64, "seed": 7, "runtime": "ggrid-ref-0.1.0"}
    t = Trace(manifest)
    t.append({"step": 0, "ev": "STEP", "applied": {"anchor": [[12, 0.1]]},
              "sigma_peak": 0.1, "norm_corr": 0.0})
    t.append({"step": 1, "ev": "OVERRIDE", "signal": "anchor", "old": 1.0, "new": 0.5, "source": "operator"})
    t.append({"step": 2, "ev": "TRIGGER", "on": "tool_call", "signal": "precision",
              "g": 0.7, "tau": 8.0, "layers": [20, 30], "source": "runtime"})
    return t


def gen_chain():
    t = _sample_trace()
    base = {"name": "valid_3rec", "manifest": t.manifest, "records": t.records, "head": t.head, "valid": True}
    _write(os.path.join(VEC, "chain", "01_valid.json"), base)

    # tamper: edit a field in record 0
    tam = json.loads(json.dumps(base))
    tam["name"] = "tampered_edit_field"
    tam["records"][0]["applied"] = {}
    tam["valid"] = False
    _write(os.path.join(VEC, "chain", "02_tampered_edit.json"), tam)

    # tamper: reorder records 1 and 2
    tre = json.loads(json.dumps(base))
    tre["name"] = "tampered_reorder"
    tre["records"][1], tre["records"][2] = tre["records"][2], tre["records"][1]
    tre["valid"] = False
    _write(os.path.join(VEC, "chain", "03_tampered_reorder.json"), tre)

    # tamper: delete a record
    tde = json.loads(json.dumps(base))
    tde["name"] = "tampered_delete"
    del tde["records"][1]
    tde["valid"] = False
    _write(os.path.join(VEC, "chain", "04_tampered_delete.json"), tde)

    # valid single-record trace (boundary)
    t1 = Trace({"model": "toy2", "seed": 1, "runtime": "ggrid-ref-0.1.0"})
    t1.append({"step": 0, "ev": "STEP", "applied": {}, "sigma_peak": 0.0, "norm_corr": 0.0})
    _write(os.path.join(VEC, "chain", "05_valid_single.json"),
           {"name": "valid_single", "manifest": t1.manifest, "records": t1.records,
            "head": t1.head, "valid": True})
    print("  chain: 5 vectors (3 tampered, 2 valid)")


# ── contract-compilation expected outputs ───────────────────────────────
def gen_contracts():
    ex = os.path.join(ROOT, "spec", "obc", "examples")
    out = {}
    for fn in sorted(os.listdir(ex)):
        if fn.endswith(".toml"):
            c = validate_contract(load_contract(os.path.join(ex, fn)))
            out[fn] = contract_hash(c)
    _write(os.path.join(VEC, "contracts.json"), out)
    print(f"  contracts: {len(out)} hashes")


if __name__ == "__main__":
    print("generating golden vectors:")
    gen_canonical()
    gen_chain()
    gen_contracts()
    print("done.")
