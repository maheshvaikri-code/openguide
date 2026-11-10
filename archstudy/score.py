"""The silent scorer: read a run's snapshot chain and measure it offline.

The agent never sees any of this. Every snapshot is scored against the VISIBLE and the
HELD-OUT rules; the final snapshot is also run against the codebase's own tests and the
hidden acceptance tests. A run is *invalid* (and says why) if the chain is broken, a
hook failed, or the workspace differs from the last snapshot. Scoring extracts snapshots
to temp directories and never writes into the workspace.

Measures (docs/briefs/arch-drift-harness.md): violations left; edits spent in violation
(snapshots with at least one violation); episodes per rule (introduced, fixed,
recurred); task success; tool calls; messages sent and commits blocked.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass, field

from archstudy import rules, snapshot, tasks

ACCEPTANCE = pathlib.Path(__file__).resolve().parent / "acceptance"
_TEST_TIMEOUT = 240


def metrics_from_series(series: list[dict]) -> dict:
    """Pure metrics from one record per snapshot.

    Each record is ``{"task": id, "visible": set of (rule, path), "held": set}``.
    """
    if not series:
        raise ValueError("a run needs at least one snapshot")
    out: dict = {"snapshots": len(series)}
    for key in ("visible", "held"):
        out[f"edits_in_violation_{key}"] = sum(1 for s in series if s[key])
        last = series[-1][key]
        out[f"{key}_final"] = len(last)
        out[f"{key}_rules_final"] = dict(Counter(rule for rule, _ in last))
    episodes: dict[str, dict] = {}
    introduced_in: dict[str, str] = {}
    by_task: Counter = Counter()
    for key in ("visible", "held"):
        present = [{rule for rule, _ in s[key]} for s in series]
        for rule in sorted(set().union(*present)):
            runs, cur = [], 0
            for here in present:
                if rule in here:
                    cur += 1
                elif cur:
                    runs.append(cur)
                    cur = 0
            open_at_end = cur > 0
            if open_at_end:
                runs.append(cur)
            episodes[rule] = {"episodes": len(runs), "fixed": len(runs) - (1 if open_at_end else 0),
                              "recurred": len(runs) > 1, "longest": max(runs)}
            first = next(i for i, here in enumerate(present) if rule in here)
            introduced_in[rule] = series[first]["task"]
    for s in series:
        if s["visible"] or s["held"]:
            by_task[s["task"]] += 1
    out["episodes"] = episodes
    out["introduced_in"] = introduced_in
    out["violating_edits_by_task"] = dict(by_task)
    return out


@dataclass
class RunScore:
    valid: bool
    problems: list[str] = field(default_factory=list)
    snapshots: int = 0
    visible_final: int = 0
    held_final: int = 0
    visible_rules_final: dict = field(default_factory=dict)
    held_rules_final: dict = field(default_factory=dict)
    edits_in_violation_visible: int = 0
    edits_in_violation_held: int = 0
    episodes: dict = field(default_factory=dict)
    introduced_in: dict = field(default_factory=dict)
    violating_edits_by_task: dict = field(default_factory=dict)
    parse_error_snapshots: int = 0
    tests_ok: bool | None = None
    acceptance: dict = field(default_factory=dict)
    acceptance_rate: float | None = None
    tool_calls: int = 0
    messages_sent: int = 0
    commit_checks: int = 0
    commits_blocked: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


_SECRETISH = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "ANTHROPIC", "OPENAI", "AWS_", "AUTH")


def _env(extra_path: pathlib.Path) -> dict:
    """The environment for code under test: the host's, minus anything that looks like a credential."""
    keep = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in _SECRETISH)}
    keep.update({"PYTHONPATH": str(extra_path), "PYTHONDONTWRITEBYTECODE": "1"})
    return keep


def _run_repo_tests(root: pathlib.Path) -> bool:
    if not (root / "tests").is_dir():
        return False
    res = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], cwd=root,
                         env=_env(root), capture_output=True, text=True, timeout=_TEST_TIMEOUT, check=False)
    return res.returncode == 0


def _run_acceptance(root: pathlib.Path, tmp: pathlib.Path) -> dict[str, bool]:
    xml = tmp / "acceptance.xml"
    repo_root = ACCEPTANCE.parent.parent
    subprocess.run([sys.executable, "-m", "pytest", str(ACCEPTANCE), "-q", "-p", "no:cacheprovider",
                    f"--junitxml={xml}", f"--rootdir={repo_root}"],
                   cwd=root, env=_env(root), capture_output=True,
                   text=True, timeout=_TEST_TIMEOUT, check=False)
    seen: dict[str, list[bool]] = {t: [] for t in tasks.TASKS}
    if xml.exists():
        for case in ET.parse(xml).getroot().iter("testcase"):
            module = (case.get("classname") or "").rsplit(".", 1)[-1]          # test_T01
            tid = module.removeprefix("test_")
            if tid in seen:
                seen[tid].append(case.find("failure") is None and case.find("error") is None)
    return {t: bool(v) and all(v) for t, v in seen.items()}


def score_run(store, workspace_final=None, *, expected_head: str | None = None,
              run_tests: bool = True) -> RunScore:
    store = pathlib.Path(store)
    problems: list[str] = []
    try:
        entries = snapshot.verify_chain(store, expected_head)
    except snapshot.ChainError as exc:
        return RunScore(False, [f"chain: {exc}"])
    errors = store / "errors.log"
    if errors.exists() and errors.read_text(encoding="utf-8").strip():
        problems.append("errors.log is not empty: a hook failed, so some edits may be unmeasured")
    if workspace_final is not None and not snapshot.final_tree_matches(store, workspace_final):
        problems.append(
            "the final tree differs from the last snapshot: the workspace changed outside the hook")
    snaps = [e for e in entries if e.kind == "snapshot"]
    if not snaps:
        return RunScore(False, problems + ["there is no snapshot"])
    series, parse_bad, task = [], 0, "initial"
    with tempfile.TemporaryDirectory(prefix="archstudy-score-") as tmp:
        tmp_path = pathlib.Path(tmp)
        for e in entries:
            if e.kind == "mark" and e.tool == "task":
                task = str(e.value)
            if e.kind != "snapshot":
                continue
            root = snapshot.extract(store, e.tree, tmp_path / f"s{e.n}")
            found = rules.check_tree(root, rules.ALL_RULES)
            parse_bad += 1 if rules.parse_errors(root) else 0
            series.append({"task": task,
                           "visible": frozenset((v.rule, v.path) for v in found if v.rule in rules.VISIBLE),
                           "held": frozenset((v.rule, v.path) for v in found if v.rule in rules.HELD_OUT)})
        m = metrics_from_series(series)
        result = RunScore(not problems, problems, m["snapshots"], m["visible_final"], m["held_final"],
                          m["visible_rules_final"], m["held_rules_final"], m["edits_in_violation_visible"],
                          m["edits_in_violation_held"], m["episodes"], m["introduced_in"],
                          m["violating_edits_by_task"], parse_bad)
        if run_tests:
            final = pathlib.Path(tmp) / f"s{snaps[-1].n}"
            result.tests_ok = _run_repo_tests(final)
            result.acceptance = _run_acceptance(final, tmp_path)
            result.acceptance_rate = sum(result.acceptance.values()) / len(result.acceptance)
    result.messages_sent = sum(1 for e in entries if e.kind == "feedback")
    checks = [e for e in entries if e.kind == "commit_check"]
    result.commit_checks = len(checks)
    result.commits_blocked = sum(1 for e in checks if e.extra.get("blocked"))
    calls = store / "calls.log"
    result.tool_calls = len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0
    return result
