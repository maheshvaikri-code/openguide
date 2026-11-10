"""The silent scorer's metrics (docs/briefs/arch-drift-harness.md, AC 7)."""
import json

import pytest

from archstudy import score, snapshot


def snap(task, visible=(), held=()):
    return {"task": task, "visible": frozenset(visible), "held": frozenset(held)}


def test_a_clean_run_has_no_violating_edits_and_no_episodes():
    m = score.metrics_from_series([snap("T01"), snap("T01"), snap("T02")])
    assert m["edits_in_violation_visible"] == 0 and m["edits_in_violation_held"] == 0
    assert m["visible_final"] == 0 and m["episodes"] == {}


def test_edits_in_violation_counts_snapshots_not_distinct_violations():
    series = [snap("T04"), snap("T04", [("V2", "a.py"), ("V1", "a.py")]),
              snap("T04", [("V2", "a.py")]), snap("T05")]
    m = score.metrics_from_series(series)
    assert m["edits_in_violation_visible"] == 2
    assert m["visible_final"] == 0


def test_the_final_violations_are_those_in_the_last_snapshot():
    m = score.metrics_from_series(
        [snap("T01", [("V2", "a.py")]), snap("T02", [("V2", "a.py"), ("V3", "b.py")])])
    assert m["visible_final"] == 2 and m["visible_rules_final"] == {"V2": 1, "V3": 1}


def test_an_episode_is_a_run_of_snapshots_where_the_rule_is_broken():
    series = [snap("a"), snap("a", [("V2", "x")]), snap("a", [("V2", "x")]), snap("a"),
              snap("a", [("V2", "y")]), snap("a")]
    ep = score.metrics_from_series(series)["episodes"]["V2"]
    assert ep["episodes"] == 2 and ep["fixed"] == 2 and ep["recurred"] is True
    assert ep["longest"] == 2


def test_an_episode_still_open_at_the_end_is_not_counted_as_fixed():
    series = [snap("a"), snap("a", [("V1", "x")]), snap("a", [("V1", "x")])]
    ep = score.metrics_from_series(series)["episodes"]["V1"]
    assert ep["episodes"] == 1 and ep["fixed"] == 0 and ep["recurred"] is False


def test_held_out_violations_are_tracked_separately_from_visible_ones():
    m = score.metrics_from_series([snap("a", held=[("H3", "x")]), snap("a", held=[("H3", "x")])])
    assert m["edits_in_violation_visible"] == 0 and m["edits_in_violation_held"] == 2
    assert m["held_final"] == 1 and m["held_rules_final"] == {"H3": 1}


def test_a_violation_is_attributed_to_the_task_in_which_it_first_appeared():
    series = [snap("T01"), snap("T04", [("V2", "x")]), snap("T04", [("V2", "x")]), snap("T05", [("V2", "x")])]
    m = score.metrics_from_series(series)
    assert m["introduced_in"] == {"V2": "T04"}
    assert m["violating_edits_by_task"] == {"T04": 2, "T05": 1}


def test_an_empty_series_is_an_error():
    with pytest.raises(ValueError):
        score.metrics_from_series([])


# -- the plumbing around it ----------------------------------------------------------------------------
@pytest.fixture
def run(tmp_path):
    from archstudy import workspace

    return workspace.create(tmp_path / "ws", tmp_path / "store", "C")


def test_a_broken_chain_makes_the_run_invalid_and_is_reported(run):
    log = run.store / "log.jsonl"
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    rec["tool"] = "Forged"
    log.write_text(json.dumps(rec, sort_keys=True) + "\n", encoding="utf-8")
    result = score.score_run(run.store, run.path, run_tests=False)
    assert result.valid is False and any("chain" in p for p in result.problems)


def test_a_hook_error_makes_the_run_invalid(run):
    (run.store / "errors.log").write_text("2026-01-01T00:00:00 ValueError: boom\n", encoding="utf-8")
    result = score.score_run(run.store, run.path, run_tests=False)
    assert result.valid is False and any("errors.log" in p for p in result.problems)


def test_changes_made_after_the_last_snapshot_make_the_run_invalid(run):
    (run.path / "app" / "sneaky.py").write_text("x = 1\n", encoding="utf-8")
    result = score.score_run(run.store, run.path, run_tests=False)
    assert result.valid is False and any("final tree" in p for p in result.problems)


def test_scoring_never_writes_into_the_workspace(run):
    before = sorted(p.relative_to(run.path).as_posix() for p in run.path.rglob("*") if ".git" not in p.parts)
    score.score_run(run.store, run.path, run_tests=True)
    after = sorted(p.relative_to(run.path).as_posix() for p in run.path.rglob("*") if ".git" not in p.parts)
    assert before == after


def test_the_untouched_template_scores_clean_with_its_tests_passing_and_most_acceptance_failing(run):
    result = score.score_run(run.store, run.path, run_tests=True)
    assert result.valid and result.visible_final == 0 and result.held_final == 0
    assert result.tests_ok is True
    # nothing has been built yet
    assert result.acceptance["T08"] is False and result.acceptance_rate == 0.0
    assert snapshot.verify_chain(run.store)[0].tool == "initial"
