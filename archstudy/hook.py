"""The Claude Code PostToolUse hook for the drift study.

Registered with matcher ``*`` so it runs after every tool call, whatever its name. In
every arm it records a snapshot of the workspace when the tree changed, silently. In
Arm B only, when the tree changed and the VISIBLE rules are violated, it returns the
rendered message as ``hookSpecificOutput.additionalContext`` (the documented channel to
the model for PostToolUse). Held-out rules are never run here. The hook always exits 0
and prints nothing otherwise; a failure is written to ``<store>/errors.log`` (which
makes the run invalid for the scorer) and never reaches the agent.

Configuration comes from the environment, set by the launcher and not by the agent:
ARCH_ARM (A|B|C), ARCH_WORKSPACE, ARCH_STORE.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time

if __package__ in (None, ""):                       # run as a script: python /opt/archstudy/hook.py
    _here = pathlib.Path(__file__).resolve().parent
    # Python puts the script's own directory first, where a module named like a stdlib
    # one would shadow it; use the parent.
    sys.path[:] = [str(_here.parent)] + [p for p in sys.path if pathlib.Path(p or ".").resolve() != _here]

from archstudy import feedback, rules, snapshot  # noqa: E402

ARMS = ("A", "B", "C")


def _log_error(store: pathlib.Path, exc: Exception) -> None:
    try:
        store.mkdir(parents=True, exist_ok=True)
        with open(store / "errors.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {type(exc).__name__}: {str(exc)[:300]}\n")
    except OSError:
        pass


def main(stdin_text: str, env=None) -> tuple[str, int]:
    env = os.environ if env is None else env
    store = pathlib.Path(env.get("ARCH_STORE", "/snap"))
    try:
        arm = env.get("ARCH_ARM", "")
        if arm not in ARMS:
            raise ValueError(f"ARCH_ARM must be one of {ARMS}, got {arm!r}")
        event = json.loads(stdin_text)
        if not isinstance(event, dict):
            raise ValueError("the hook input is not a JSON object")
        workspace = pathlib.Path(env.get("ARCH_WORKSPACE", "/workspace"))
        snap = snapshot.Snapshotter(workspace, store)
        snap.init()
        # a cost proxy: one line per tool call
        with open(store / "calls.log", "a", encoding="utf-8") as f:
            f.write(str(event.get("tool_name", "")).replace("\n", " ") + "\n")
        entry = snap.snapshot(str(event.get("tool_name", "")), str(event.get("tool_use_id", "")))
        if arm == "B" and entry is not None:
            violations = rules.check_tree(workspace, rules.VISIBLE)
            if violations:
                msg = feedback.render(violations)
                snap.note("feedback", violations=len(violations),
                          sha256=hashlib.sha256(msg.encode()).hexdigest())
                out = {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                              "additionalContext": msg}}
                return json.dumps(out), 0
    except Exception as exc:                        # noqa: BLE001 - the agent must never see a harness failure
        _log_error(store, exc)
    return "", 0


if __name__ == "__main__":
    text, code = main(sys.stdin.read())
    if text:
        sys.stdout.write(text)
    raise SystemExit(code)
