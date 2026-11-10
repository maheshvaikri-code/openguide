"""Scripted stand-in agents: replay a task script through the real hook and the real git
commit check, with no model.

Four policies, each deciding what to do at the two shock tasks (every other task is done
properly):
  compliant   does the work within the rules
  shortcut    takes the shortcut the prompt asked for, ignores any feedback, never fixes it
  disguised   takes a shortcut that passes the visible checks and breaks a held-out rule
  responsive  takes the shortcut, but fixes it as soon as it is told (after the edit in
              Arm B, at the rejected commit in Arm A)

One op is one tool call; after each, the PostToolUse hook runs with a real event on
stdin, and any feedback it returns is what the agent "sees". This validates the
measuring chain; it says nothing about what a real model does.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

from archstudy import hook, score, snapshot, solutions, tasks, workspace

POLICIES = ("compliant", "shortcut", "disguised", "responsive")
HOOK_SCRIPT = pathlib.Path(hook.__file__)


class Session:
    """One workspace, driven like an agent session."""

    def __init__(self, ws: workspace.Workspace, *, subprocess_hook: bool = False):
        self.ws, self.subprocess_hook, self.n = ws, subprocess_hook, 0
        self.env = {**os.environ, **workspace.hook_env(ws)}
        self.snap = snapshot.Snapshotter(ws.path, ws.store)

    def _fire(self, tool: str, tool_input: dict) -> str:
        self.n += 1
        event = workspace.event(self.ws, tool, tool_input, f"toolu_{self.n}")
        if self.subprocess_hook:
            res = subprocess.run([sys.executable, str(HOOK_SCRIPT)], input=event,
                                 capture_output=True, text=True,
                                 env=self.env, cwd=self.ws.store, check=False)
            out = res.stdout
        else:
            out, _ = hook.main(event, workspace.hook_env(self.ws))
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""

    def tool_call(self, op: solutions.Op) -> str:
        solutions.apply(self.ws.path, op)
        return self._fire("Write" if op.mode == "write" else "Edit", {"file_path": op.path})

    def restore(self, path: str, original: str | None) -> str:
        p = self.ws.path / path
        if original is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(original, encoding="utf-8", newline="\n")
        return self._fire("Write", {"file_path": path})

    def read(self, path: str) -> str | None:
        p = self.ws.path / path
        return p.read_text(encoding="utf-8") if p.exists() else None

    def commit(self, message: str) -> tuple[bool, str]:
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.ws.path, env=self.env,
                                  capture_output=True, text=True)

        git("add", "-A")
        res = git("commit", "-q", "-m", message, "--allow-empty")
        self._fire("Bash", {"command": f"git commit -m {message!r}"})
        return res.returncode == 0, res.stderr


def _do_properly(s: Session, tid: str) -> None:
    for op in solutions.solution(tid, "compliant"):
        s.tool_call(op)
    s.commit(tid)


def _do_shock(s: Session, tid: str, policy: str, arm: str) -> None:
    variant = "disguised" if policy == "disguised" else "shortcut"
    ops = solutions.solution(tid, variant)
    originals = {op.path: s.read(op.path) for op in ops}
    fixed = False

    def fix() -> None:
        for path, original in originals.items():
            s.restore(path, original)
        for op in solutions.solution(tid, "compliant"):
            s.tool_call(op)

    for op in ops:
        told = s.tool_call(op)
        if told and policy == "responsive":                        # Arm B: told right after the edit
            fix()
            fixed = True
            break
    ok, message = s.commit(tid)
    if not ok and message and policy == "responsive" and not fixed:   # Arm A: told at the rejected commit
        fix()
        s.commit(tid)


def run_standin(policy: str, arm: str, script: tasks.Script, dest, *, tasks_limit: int | None = None,
                subprocess_hook: bool = False, run_tests: bool = True) -> score.RunScore:
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}")
    dest = pathlib.Path(dest)
    ws = workspace.create(dest / "ws", dest / "store", arm)
    s = Session(ws, subprocess_hook=subprocess_hook)
    for tid in script.order[:tasks_limit]:
        s.snap.mark("task", tid)
        if tasks.TASKS[tid].shock and policy != "compliant":
            _do_shock(s, tid, policy, arm)
        else:
            _do_properly(s, tid)
    return score.score_run(ws.store, ws.path, run_tests=run_tests)
