"""Silent snapshots into a hash-chained log (docs/briefs/arch-drift-harness.md, AC 6)."""
import json
import threading

import pytest

from archstudy import snapshot


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    (w / "app").mkdir(parents=True)
    (w / "app" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return w


@pytest.fixture
def snap(tmp_path, ws):
    s = snapshot.Snapshotter(ws, tmp_path / "store")
    s.init()
    return s


def test_the_first_snapshot_records_the_tree_and_an_unchanged_tree_records_nothing(snap):
    first = snap.snapshot("Write")
    assert first is not None and len(first.tree) == 40
    assert snap.snapshot("Bash") is None


def test_a_change_gives_a_new_snapshot_with_a_different_tree(snap, ws):
    a = snap.snapshot("Write")
    (ws / "app" / "a.py").write_text("x = 2\n", encoding="utf-8")
    b = snap.snapshot("Edit")
    assert b is not None and b.tree != a.tree and b.tool == "Edit"


def test_git_dirs_and_bytecode_are_not_part_of_the_snapshot(snap, ws):
    snap.snapshot("Write")
    (ws / ".git").mkdir()
    (ws / ".git" / "config").write_text("x", encoding="utf-8")
    (ws / "app" / "__pycache__").mkdir()
    (ws / "app" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\x00")
    (ws / ".pytest_cache").mkdir()
    (ws / ".pytest_cache" / "v").write_text("x", encoding="utf-8")
    assert snap.snapshot("Bash") is None


def test_the_chain_verifies_and_carries_marks_and_snapshots_in_order(snap, ws):
    snap.mark("task", 1)
    snap.snapshot("Write")
    (ws / "app" / "a.py").write_text("x = 3\n", encoding="utf-8")
    snap.snapshot("Edit")
    snap.mark("task", 2)
    entries = snapshot.verify_chain(snap.store)
    assert [e.kind for e in entries] == ["mark", "snapshot", "snapshot", "mark"]
    assert [e.n for e in entries] == [0, 1, 2, 3]
    assert entries[0].value == 1 and entries[3].value == 2


def _lines(snap):
    return (snap.store / "log.jsonl").read_text(encoding="utf-8").splitlines()


def test_editing_an_entry_breaks_the_chain(snap, ws):
    snap.snapshot("Write")
    (ws / "app" / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap.snapshot("Edit")
    lines = _lines(snap)
    rec = json.loads(lines[0])
    rec["tool"] = "Forged"
    lines[0] = json.dumps(rec, sort_keys=True)
    (snap.store / "log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(snapshot.ChainError):
        snapshot.verify_chain(snap.store)


def test_deleting_or_reordering_entries_breaks_the_chain(snap, ws):
    for i in range(3):
        (ws / "app" / "a.py").write_text(f"x = {i}\n", encoding="utf-8")
        snap.snapshot("Edit")
    lines = _lines(snap)
    path = snap.store / "log.jsonl"
    path.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")        # delete the middle one
    with pytest.raises(snapshot.ChainError):
        snapshot.verify_chain(snap.store)
    path.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n", encoding="utf-8")   # reorder
    with pytest.raises(snapshot.ChainError):
        snapshot.verify_chain(snap.store)


def test_truncating_the_tail_is_detected_against_the_recorded_head(snap, ws):
    snap.snapshot("Write")
    (ws / "app" / "a.py").write_text("x = 2\n", encoding="utf-8")
    snap.snapshot("Edit")
    head = snapshot.verify_chain(snap.store)[-1].hash
    (snap.store / "log.jsonl").write_text(_lines(snap)[0] + "\n", encoding="utf-8")
    snapshot.verify_chain(snap.store)                                           # still a valid chain...
    with pytest.raises(snapshot.ChainError):
        # ...but not the one that was recorded
        snapshot.verify_chain(snap.store, expected_head=head)


def test_the_final_tree_must_match_the_workspace(snap, ws):
    snap.snapshot("Write")
    assert snapshot.final_tree_matches(snap.store, ws) is True
    (ws / "app" / "a.py").write_text("x = changed outside any hook\n", encoding="utf-8")
    assert snapshot.final_tree_matches(snap.store, ws) is False


def test_a_snapshot_can_be_extracted_to_a_directory(snap, ws, tmp_path):
    e = snap.snapshot("Write")
    out = tmp_path / "out"
    snapshot.extract(snap.store, e.tree, out)
    assert (out / "app" / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_concurrent_snapshots_keep_the_chain_valid(snap, ws):
    def work(i):
        (ws / "app" / f"f{i}.py").write_text(f"x = {i}\n", encoding="utf-8")
        snap.snapshot("Write")

    threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = snapshot.verify_chain(snap.store)
    assert [e.n for e in entries] == list(range(len(entries)))
    assert 1 <= len(entries) <= 6


def test_the_store_may_not_live_inside_the_workspace(ws):
    with pytest.raises(ValueError):
        snapshot.Snapshotter(ws, ws / "store")


def test_a_hook_never_writes_into_the_workspace(snap, ws):
    before = sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*"))
    snap.snapshot("Write")
    assert sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*")) == before


def test_a_gitignore_in_the_workspace_cannot_hide_files_from_the_snapshot(snap, ws, tmp_path):
    (ws / ".gitignore").write_text("app/\n*.py\n", encoding="utf-8")
    e = snap.snapshot("Write")
    out = tmp_path / "out"
    snapshot.extract(snap.store, e.tree, out)
    assert (out / "app" / "a.py").exists()
