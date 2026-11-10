"""Silent working-tree snapshots, kept outside the workspace in a separate git dir, with a hash-chained log.

The snapshot is the tree of the whole workspace (git plumbing against a bare repository
in the store, so nothing is written into the workspace and the agent's own ``.git`` is
untouched). The log is append-only and hash-chained: each entry carries the hash of the
one before. ``verify_chain`` refuses an edited, reordered or deleted entry, and, given
the head hash the harness recorded from outside, a truncated tail.
``final_tree_matches`` refuses a run whose last snapshot is not the workspace as it
ended.

Snapshots ignore the workspace's own ``.gitignore`` (an agent must not be able to hide
files by ignoring them).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

GENESIS = "0" * 64
_EXCLUDES = (":(exclude).git", ":(exclude).pytest_cache", ":(exclude)**/__pycache__/**", ":(exclude)**/*.pyc")
_GIT_TIMEOUT = 60


class ChainError(Exception):
    """The log is not the chain the harness wrote."""


@dataclass(frozen=True)
class Entry:
    n: int
    kind: str                       # snapshot | mark | feedback | commit_check
    tool: str
    tool_use_id: str
    tree: str
    value: Any
    extra: dict = field(default_factory=dict)
    ts: float = 0.0
    prev: str = GENESIS
    hash: str = ""


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _entry(rec: dict) -> Entry:
    return Entry(rec["n"], rec["kind"], rec["tool"], rec["tool_use_id"], rec["tree"], rec["value"],
                 rec.get("extra", {}), rec["ts"], rec["prev"], rec["hash"])


def _git(git_dir, work_tree, *args, index=None, binary=False):
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "-c", "core.quotepath=off",
           "-c", "core.excludesFile=", f"--git-dir={git_dir}"]
    if work_tree is not None:
        cmd.append(f"--work-tree={work_tree}")
    res = subprocess.run(cmd + list(args), capture_output=True, env=env, timeout=_GIT_TIMEOUT, check=False)
    if res.returncode != 0:
        detail = res.stderr.decode(errors="replace").strip()[:300]
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {detail}")
    return res.stdout if binary else res.stdout.decode().strip()


def _read_lines(store: pathlib.Path) -> list[str]:
    path = store / "log.jsonl"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def verify_chain(store, expected_head: str | None = None) -> list[Entry]:
    store = pathlib.Path(store)
    entries: list[Entry] = []
    prev = GENESIS
    for i, line in enumerate(_read_lines(store)):
        try:
            rec = json.loads(line)
            ok = rec["n"] == i and rec["prev"] == prev and rec["hash"] == _digest(rec)
        except (ValueError, KeyError, TypeError) as exc:
            raise ChainError(f"entry {i} is not a valid record: {exc}") from exc
        if not ok:
            raise ChainError(f"the chain is broken at entry {i}")
        entries.append(_entry(rec))
        prev = rec["hash"]
    if expected_head is not None and prev != expected_head:
        raise ChainError("the log does not end at the head that was recorded")
    return entries


def _tree_of(store: pathlib.Path, workspace: pathlib.Path, index: pathlib.Path) -> str:
    git_dir = store / "snap.git"
    _git(git_dir, workspace, "add", "-A", "-f", "--", ".", *_EXCLUDES, index=index)
    return _git(git_dir, workspace, "write-tree", index=index)


def final_tree_matches(store, workspace) -> bool:
    """Is the last recorded snapshot exactly the workspace as it is now?"""
    store, workspace = pathlib.Path(store), pathlib.Path(workspace)
    snaps = [e for e in verify_chain(store) if e.kind == "snapshot"]
    if not snaps:
        return False
    with tempfile.TemporaryDirectory(prefix="archstudy-idx-") as tmp:
        return _tree_of(store, workspace, pathlib.Path(tmp) / "index") == snaps[-1].tree


def extract(store, tree: str, dest) -> pathlib.Path:
    """Write the files of a snapshot tree into ``dest`` (created if missing)."""
    dest = pathlib.Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    data = _git(pathlib.Path(store) / "snap.git", None, "archive", "--format=tar", tree, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    return dest


class Snapshotter:
    def __init__(self, workspace, store):
        self.workspace = pathlib.Path(workspace).resolve()
        self.store = pathlib.Path(store).resolve()
        if self.store == self.workspace or self.workspace in self.store.parents:
            raise ValueError("the snapshot store must not live inside the workspace")
        self.git_dir = self.store / "snap.git"
        self._index = self.store / "index"

    def init(self) -> None:
        self.store.mkdir(parents=True, exist_ok=True)
        if not self.git_dir.exists():
            _git(self.git_dir, None, "init", "--bare", "-q", str(self.git_dir))

    @contextmanager
    def _lock(self) -> Iterator[None]:
        path, deadline = self.store / "lock", time.time() + 30
        while True:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if time.time() > deadline:
                    raise TimeoutError("could not take the snapshot lock") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _append(self, **fields) -> Entry:
        lines = _read_lines(self.store)
        last = json.loads(lines[-1]) if lines else None
        rec = {"n": len(lines), "kind": "", "tool": "", "tool_use_id": "", "tree": "",
               "value": None, "extra": {},
               "ts": round(time.time(), 3), "prev": last["hash"] if last else GENESIS}
        rec.update(fields)
        rec["hash"] = _digest(rec)
        with open(self.store / "log.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return _entry(rec)

    def _last_tree(self) -> str:
        for line in reversed(_read_lines(self.store)):
            rec = json.loads(line)
            if rec["kind"] == "snapshot":
                return rec["tree"]
        return ""

    def snapshot(self, tool: str, tool_use_id: str = "") -> Entry | None:
        """Record the workspace tree if it changed since the last snapshot; silent either way."""
        with self._lock():
            _git(self.git_dir, self.workspace, "add", "-A", "-f", "--", ".", *_EXCLUDES, index=self._index)
            tree = _git(self.git_dir, self.workspace, "write-tree", index=self._index)
            if tree == self._last_tree():
                return None
            return self._append(kind="snapshot", tool=tool, tool_use_id=tool_use_id, tree=tree)

    def mark(self, name: str, value: Any) -> Entry:
        with self._lock():
            return self._append(kind="mark", tool=name, value=value)

    def note(self, kind: str, **extra) -> Entry:
        """Record that something happened (a message was sent, a commit was checked) in the same chain."""
        with self._lock():
            return self._append(kind=kind, tree=self._last_tree(), extra=extra)
