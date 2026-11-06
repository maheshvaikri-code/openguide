"""Rebuild the saved real-model runs with message text, replaying the model's recorded replies.

    python scripts/rebuild_real_db.py                      # into .console-demo/real-model.db
    python scripts/rebuild_real_db.py --db scratch.db      # elsewhere

Reads the committed raw results in benchmarks/results/qwen2.5-1.5b/. No GPU needed. Every replayed turn
must reproduce the recorded drift, action and rule results exactly, or nothing is written for that file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import real_rebuild as rb  # noqa: E402
from guidancegrid.store import Store  # noqa: E402

RESULTS = os.path.join(ROOT, "benchmarks", "results", "qwen2.5-1.5b")
FILES = (("real_recovery_results_shock.json", "shock"), ("real_ablation_results.json", "abl"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=os.path.join(ROOT, ".console-demo", "real-model.db"))
    ap.add_argument("--results", default=RESULTS)
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    store = Store(args.db)
    total = 0
    for name, tag in FILES:
        path = os.path.join(args.results, name)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        try:
            n = rb.rebuild(saved, store, tag)
        except rb.FidelityError as e:
            print(f"{name}: NOT rebuilt. {e}", file=sys.stderr)
            return 1
        print(f"{name}: {n} runs replayed and verified turn by turn, now with message text", flush=True)
        total += n
    print(f"done: {total} runs written to {args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
