"""Dry run of the architecture-drift study harness with scripted stand-in agents.
Makes no model or API call.

    python scripts/arch_dryrun.py            # all policies x arms, the real hook as a subprocess, ~10 minutes
    python scripts/arch_dryrun.py --quick    # first 9 tasks, in-process hook, no test runs (~1 minute)

It prints one row per (policy, arm) and checks the registered expectations
(archstudy/dryrun.py). Exit code 0 only if every expectation holds. ASCII output.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from archstudy import dryrun, standin, tasks  # noqa: E402


def main() -> int:
    # the first paragraph of the module docstring, re-joined onto one line
    ap = argparse.ArgumentParser(description=" ".join(__doc__.split("\n\n")[0].split()))
    ap.add_argument("--seed", type=int, default=0, help="task-script seed")
    ap.add_argument("--quick", action="store_true", help="first 9 tasks, in-process hook, no test runs")
    args = ap.parse_args()
    script = tasks.build_script(args.seed)
    print(f"script seed {args.seed}  hash {script.hash[:16]}  order {' '.join(script.order)}")
    print(f"shocks: position 4 = {script.order[3]}, position 9 = {script.order[8]}\n")
    t = time.time()
    with tempfile.TemporaryDirectory(prefix="archstudy-dryrun-") as tmp:
        with_tests = () if args.quick else tuple((p, a) for p in standin.POLICIES for a in dryrun.ARMS)
        results = dryrun.run_matrix(script, tmp, tasks_limit=9 if args.quick else None,
                                    subprocess_hook=not args.quick, with_tests=with_tests)
    head = (f"{'policy':11s} {'arm':3s} {'valid':5s} {'vis_left':8s} {'held_left':9s} "
            f"{'viol_edits(vis/held)':20s} "
            f"{'msgs':4s} {'blocked':7s} {'tasks_ok':8s} {'calls':5s}")
    print(head)
    for (policy, arm), r in results.items():
        ok = "-" if r.acceptance_rate is None else f"{r.acceptance_rate:.0%}"
        print(f"{policy:11s} {arm:3s} {str(r.valid):5s} {r.visible_final:<8d} {r.held_final:<9d} "
              f"{r.edits_in_violation_visible:>8d} /{r.edits_in_violation_held:<10d} {r.messages_sent:<4d} "
              f"{r.commits_blocked:<7d} {ok:8s} {r.tool_calls:<5d}")
    bad = dryrun.check_expectations(results)
    print(f"\n{len(results)} runs in {time.time() - t:.0f}s")
    if bad:
        print("EXPECTATIONS FAILED:")
        for line in bad:
            print("  -", line)
        return 1
    print("all expectations hold: the scorer tells the four stand-in policies apart in every arm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
