"""The hook adapter and the commit check (docs/briefs/arch-drift-harness.md, ACs 4 and 5)."""
import json
import pathlib
import subprocess
import sys

import pytest

from archstudy import feedback, hook, precommit, rules, snapshot, workspace

HOOK_SCRIPT = pathlib.Path(hook.__file__)
VISIBLE_BAD = "from app.repositories import orders\n"             # V1 from a handler
HELD_OUT_BAD = "def f(conn):\n    return conn.execute('select 1')\n"   # H2 from a service


def make(tmp_path, arm):
    return workspace.create(tmp_path / "ws", tmp_path / "store", arm)


def write(ws, rel, text):
    p = ws.path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def fire(ws, tool="Write", n=1):
    return hook.main(workspace.event(ws, tool, {"file_path": "x"}, f"toolu_{n}"), workspace.hook_env(ws))


def log(ws):
    return snapshot.verify_chain(ws.store)


def test_arms_a_and_c_stay_completely_silent_even_with_a_violation(tmp_path):
    for arm in ("A", "C"):
        ws = workspace.create(tmp_path / arm / "ws", tmp_path / arm / "store", arm)
        write(ws, "app/handlers/orders.py", VISIBLE_BAD)
        assert fire(ws) == ("", 0)
        assert any(e.kind == "snapshot" for e in log(ws))


def test_arm_b_feeds_back_a_visible_violation_as_additional_context(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    out, code = fire(ws)
    assert code == 0
    body = json.loads(out)["hookSpecificOutput"]
    assert body["hookEventName"] == "PostToolUse"
    assert "V1" in body["additionalContext"] and "app/handlers/orders.py:1" in body["additionalContext"]
    assert rules.adr_text("V1").splitlines()[0] in body["additionalContext"]


def test_arm_b_is_silent_when_the_tree_is_clean(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/handlers/orders.py", "from app.services import orders\n")
    assert fire(ws) == ("", 0)


def test_arm_b_never_feeds_back_a_held_out_violation(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/services/x.py", HELD_OUT_BAD)
    assert fire(ws) == ("", 0)
    assert any(e.kind == "snapshot" for e in log(ws))            # but it is still recorded for the scorer


def test_arm_b_speaks_only_when_the_tree_changed(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    assert fire(ws, n=1)[0] != ""
    assert fire(ws, "Bash", n=2) == ("", 0)                       # a read-only command: nothing new to say
    write(ws, "app/handlers/orders.py", VISIBLE_BAD + "# touched\n")
    assert fire(ws, n=3)[0] != ""


def test_arm_b_goes_quiet_once_the_violation_is_fixed(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    fire(ws, n=1)
    write(ws, "app/handlers/orders.py", "from app.services import orders\n")
    assert fire(ws, n=2) == ("", 0)


def test_every_message_sent_is_recorded_in_the_chain(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    out, _ = fire(ws)
    sent = [e for e in log(ws) if e.kind == "feedback"]
    assert len(sent) == 1 and sent[0].extra["violations"] == 1 and len(sent[0].extra["sha256"]) == 64
    assert json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_the_hook_exits_zero_and_says_nothing_on_garbage_or_a_bad_arm_and_logs_why(tmp_path):
    ws = make(tmp_path, "B")
    assert hook.main("not json", workspace.hook_env(ws)) == ("", 0)
    bad_arm_env = {**workspace.hook_env(ws), "ARCH_ARM": "Z"}
    assert hook.main(workspace.event(ws, "Write", {}, "t"), bad_arm_env) == ("", 0)
    errors = (ws.store / "errors.log").read_text(encoding="utf-8")
    assert "not json" not in errors and errors.count("\n") >= 2


def test_a_hook_run_changes_nothing_in_the_workspace(tmp_path):
    ws = make(tmp_path, "B")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    before = {p.relative_to(ws.path).as_posix(): p.read_bytes() for p in ws.path.rglob("*") if p.is_file()
              and ".git" not in p.parts}
    fire(ws)
    after = {p.relative_to(ws.path).as_posix(): p.read_bytes() for p in ws.path.rglob("*") if p.is_file()
             and ".git" not in p.parts}
    assert before == after


# -- Arm A: the commit check ------------------------------------------------------------------------------
def test_the_commit_check_blocks_a_visible_violation_in_arm_a_with_the_same_message_as_arm_b(tmp_path):
    a = workspace.create(tmp_path / "a" / "ws", tmp_path / "a" / "store", "A")
    b = workspace.create(tmp_path / "b" / "ws", tmp_path / "b" / "store", "B")
    for w in (a, b):
        write(w, "app/handlers/orders.py", VISIBLE_BAD)
    res = precommit.run(workspace.hook_env(a))
    assert res.code == 1
    sent = json.loads(fire(b)[0])["hookSpecificOutput"]["additionalContext"]
    # byte-identical content: only the timing differs
    assert res.stderr.rstrip("\n") == sent
    assert res.stderr.encode() == (feedback.render(rules.check_tree(a.path, rules.VISIBLE)) + "\n").encode()


def test_the_commit_check_lets_a_clean_tree_and_held_out_violations_through_silently(tmp_path):
    ws = make(tmp_path, "A")
    write(ws, "app/services/x.py", HELD_OUT_BAD)
    res = precommit.run(workspace.hook_env(ws))
    assert (res.code, res.stderr) == (0, "")


def test_the_commit_check_only_gates_arm_a(tmp_path):
    for arm in ("B", "C"):
        ws = workspace.create(tmp_path / arm / "ws", tmp_path / arm / "store", arm)
        write(ws, "app/handlers/orders.py", VISIBLE_BAD)
        assert precommit.run(workspace.hook_env(ws)).code == 0


def test_git_really_runs_the_commit_check_and_rejects_the_commit_in_arm_a(tmp_path):
    ws = make(tmp_path, "A")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    env = {**__import__("os").environ, **workspace.hook_env(ws)}
    run = lambda *a: subprocess.run(["git", *a], cwd=ws.path, env=env, capture_output=True, text=True)   # noqa: E731
    run("add", "-A")
    res = run("commit", "-m", "task")
    assert res.returncode != 0 and "V1" in res.stderr
    write(ws, "app/handlers/orders.py", "from app.services import orders\n")
    run("add", "-A")
    assert run("commit", "-m", "task").returncode == 0
    checks = [e for e in log(ws) if e.kind == "commit_check"]
    assert [c.extra["blocked"] for c in checks] == [True, False]


# -- the real script, as Claude Code runs it ----------------------------------------------------------------
@pytest.mark.parametrize("arm,speaks", [("B", True), ("A", False), ("C", False)])
def test_the_script_runs_standalone_from_another_directory(tmp_path, arm, speaks):
    ws = workspace.create(tmp_path / "ws", tmp_path / "store", arm)
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    env = {**__import__("os").environ, **workspace.hook_env(ws)}
    res = subprocess.run([sys.executable, str(HOOK_SCRIPT)], input=workspace.event(ws, "Write", {}, "t1"),
                         capture_output=True, text=True, cwd=tmp_path, env=env)
    assert res.returncode == 0 and res.stderr == ""
    assert (res.stdout != "") is speaks


def _image_dir(tmp_path):
    """The agent's image layout: only the files the Dockerfile copies into /opt/archstudy."""
    import re
    import shutil

    root = pathlib.Path(hook.__file__).resolve().parent
    dockerfile = re.sub(r"\\\r?\n", " ", (root / "container" / "Dockerfile").read_text(encoding="utf-8"))
    image = tmp_path / "opt" / "archstudy"
    image.mkdir(parents=True)
    for line in dockerfile.splitlines():
        m = re.match(r"COPY (.+) /opt/archstudy/(.*)$", line.strip())
        if not m:
            continue
        for src in m.group(1).split():
            src_path = root.parent / src
            dest = image / m.group(2)
            dest.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                shutil.copytree(src_path, dest, dirs_exist_ok=True)
            else:
                shutil.copy(src_path, dest / src_path.name)
    return image


def test_the_hook_runs_from_an_image_like_directory_that_has_no_held_out_module(tmp_path):
    image = _image_dir(tmp_path)
    assert not (image / "heldout.py").exists() and not (image / "score.py").exists()
    assert (image / "hook.py").exists() and (image / "codebase" / "docs" / "adr" / "001-layering.md").exists()
    ws = workspace.create(tmp_path / "ws", tmp_path / "store", "B")
    write(ws, "app/handlers/orders.py", VISIBLE_BAD)
    env = {**__import__("os").environ, **workspace.hook_env(ws)}
    res = subprocess.run([sys.executable, str(image / "hook.py")],
                         input=workspace.event(ws, "Write", {}, "t1"),
                         capture_output=True, text=True, cwd=tmp_path, env=env)
    assert res.returncode == 0 and res.stderr == ""
    assert "V1" in json.loads(res.stdout)["hookSpecificOutput"]["additionalContext"]
    assert not (ws.store / "errors.log").exists()
    probe = subprocess.run([sys.executable, "-c", "import archstudy.heldout"], capture_output=True, text=True,
                           cwd=image.parent, env={**env, "PYTHONPATH": str(image.parent)})
    assert probe.returncode != 0 and "heldout" in probe.stderr                # it really is absent there


def test_every_tool_call_is_counted_as_a_cost_proxy(tmp_path):
    ws = make(tmp_path, "C")
    for i in range(4):
        fire(ws, "Bash", n=i)
    assert (ws.store / "calls.log").read_text(encoding="utf-8").splitlines() == ["Bash"] * 4
