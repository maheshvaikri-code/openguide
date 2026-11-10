"""The commit-time check for Arm A (installed as the workspace's git pre-commit hook).

Runs the same visible-rule checks as Arm B and prints the same message, only at commit
time. It gates only Arm A; in other arms it does nothing. It looks at the working tree
(a deliberate simplification: a partially staged commit is checked as a whole).
"""
from __future__ import annotations

import os
import pathlib
import sys
from dataclasses import dataclass

if __package__ in (None, ""):                       # run as a script from a git hook
    _here = pathlib.Path(__file__).resolve().parent
    sys.path[:] = [str(_here.parent)] + [p for p in sys.path if pathlib.Path(p or ".").resolve() != _here]

from archstudy import feedback, rules, snapshot  # noqa: E402


@dataclass(frozen=True)
class Result:
    code: int
    stderr: str


def run(env=None) -> Result:
    env = os.environ if env is None else env
    if env.get("ARCH_ARM") != "A":
        return Result(0, "")
    workspace = pathlib.Path(env.get("ARCH_WORKSPACE") or os.getcwd())
    violations = rules.check_tree(workspace, rules.VISIBLE)
    store = env.get("ARCH_STORE")
    if store:
        try:
            snap = snapshot.Snapshotter(workspace, store)
            snap.init()
            snap.note("commit_check", violations=len(violations), blocked=bool(violations))
        except Exception as exc:                    # noqa: BLE001 - recorded, never shown; the scorer treats it as invalid
            try:
                with open(pathlib.Path(store) / "errors.log", "a", encoding="utf-8") as f:
                    f.write(f"commit_check {type(exc).__name__}: {str(exc)[:300]}\n")
            except OSError:
                pass
    if violations:
        return Result(1, feedback.render(violations) + "\n")
    return Result(0, "")


if __name__ == "__main__":
    res = run()
    sys.stderr.write(res.stderr)
    raise SystemExit(res.code)
