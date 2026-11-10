"""Create a study workspace: the template codebase in a fresh git repository, set up for one arm.

The arm decides which checks exist. Arm A gets a git pre-commit hook; Arm B and C do not
(Arm B's checks run from the PostToolUse hook, which the launcher registers outside the
workspace). The snapshot store is created outside the workspace.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
from dataclasses import dataclass

from archstudy import snapshot

TEMPLATE = pathlib.Path(__file__).resolve().parent / "codebase"
PRECOMMIT = pathlib.Path(__file__).resolve().parent / "precommit.py"
ARMS = ("A", "B", "C")


@dataclass(frozen=True)
class Workspace:
    path: pathlib.Path
    store: pathlib.Path
    arm: str


def _git(path, *args):
    subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=path, check=True, capture_output=True)


def create(dest, store, arm: str, python: str | None = None) -> Workspace:
    if arm not in ARMS:
        raise ValueError(f"arm must be one of {ARMS}")
    dest, store = pathlib.Path(dest).resolve(), pathlib.Path(store).resolve()
    shutil.copytree(TEMPLATE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "user.name", "study-agent")
    _git(dest, "config", "user.email", "study-agent@example.invalid")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "initial codebase")
    if arm == "A":
        hook = dest / ".git" / "hooks" / "pre-commit"
        hook.write_text(f'#!/bin/sh\nexec "{pathlib.Path(python or sys.executable).as_posix()}" '
                        f'"{PRECOMMIT.as_posix()}"\n', encoding="utf-8", newline="\n")
        hook.chmod(0o755)
    snap = snapshot.Snapshotter(dest, store)
    snap.init()
    snap.snapshot("initial")                          # the baseline: the first edit is then a change
    return Workspace(dest, store, arm)


def hook_env(ws: Workspace) -> dict[str, str]:
    return {"ARCH_ARM": ws.arm, "ARCH_WORKSPACE": str(ws.path), "ARCH_STORE": str(ws.store)}


def event(ws: Workspace, tool_name: str, tool_input: dict, tool_use_id: str) -> str:
    """A PostToolUse event as Claude Code delivers it on the hook's stdin."""
    return json.dumps({"session_id": "dryrun", "transcript_path": "", "cwd": str(ws.path),
                       "permission_mode": "default",
                       "hook_event_name": "PostToolUse", "tool_name": tool_name, "tool_input": tool_input,
                       "tool_response": {}, "tool_use_id": tool_use_id})
