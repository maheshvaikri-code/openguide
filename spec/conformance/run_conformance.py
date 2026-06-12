"""Independent conformance runner — the Phase 0 gate.

This script re-implements the canonical encoding and chain verification from
the SPEC DOCS ALONE (spec/trace/README.md §1-3). It deliberately does NOT
import guidancegrid. If it reproduces every golden hash and correctly accepts
valid chains / rejects tampered ones, the spec is self-sufficient for a second
implementation (e.g. the Node runner) to interoperate.

Run from repo root:  python spec/conformance/run_conformance.py
Exit code 0 = all vectors pass.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VEC = os.path.join(HERE, "vectors")


# ── canonical encoding, reimplemented from spec/trace/README.md §1 ───────
def canon(obj):
    if obj is None or isinstance(obj, bool) or isinstance(obj, int) and not isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return float(f"{obj:.9g}")          # rule 2: 9 significant digits
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):                # rule 3: keys to str, sorted
        return {str(k): canon(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):       # rule 4: order preserved
        return [canon(v) for v in obj]
    raise TypeError(f"non-canonical type: {type(obj)}")


def canonical_json(obj):
    # rule 5: sorted keys, no whitespace, ASCII-escaped
    return json.dumps(canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def chash(obj):
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# ── chain verification, reimplemented from spec/trace/README.md §3 ───────
def verify(manifest, records, stored_head):
    head = chash(manifest)                    # genesis
    for rec in records:
        if rec.get("prev") != head:
            return False
        head = chash(rec)
    return head == stored_head


# ── runner ───────────────────────────────────────────────────────────────
def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run():
    passed = failed = 0

    def check(cond, label):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL: {label}")

    # canonical vectors
    cdir = os.path.join(VEC, "canonical")
    for fn in sorted(os.listdir(cdir)):
        v = _load(os.path.join(cdir, fn))
        check(canonical_json(v["input"]) == v["canonical"], f"canonical/{fn}: encoding")
        check(chash(v["input"]) == v["hash"], f"canonical/{fn}: hash")

    # chain vectors
    hdir = os.path.join(VEC, "chain")
    for fn in sorted(os.listdir(hdir)):
        v = _load(os.path.join(hdir, fn))
        got = verify(v["manifest"], v["records"], v["head"])
        check(got == v["valid"], f"chain/{fn}: expected valid={v['valid']}, got {got}")

    # contract hashes (canonical hash of the decoded TOML object)
    contracts = _load(os.path.join(VEC, "contracts.json"))
    try:
        try:
            import tomllib as toml
        except ModuleNotFoundError:
            import tomli as toml  # type: ignore
        ex = os.path.join(HERE, "..", "obc", "examples")
        for fn, expected in contracts.items():
            with open(os.path.join(ex, fn), "rb") as f:
                obj = toml.load(f)
            check(chash(obj) == expected, f"contracts/{fn}: hash")
    except ModuleNotFoundError:
        print("  SKIP: no TOML reader available for contract vectors")

    total = passed + failed
    print(f"\nconformance: {passed}/{total} checks passed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
