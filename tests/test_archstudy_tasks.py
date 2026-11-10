"""The task script (docs/briefs/arch-drift-harness.md, AC 3)."""
import pathlib

from archstudy import tasks

SEEDS = range(200)


def test_there_are_twelve_distinct_tasks_two_of_them_shocks():
    assert len(tasks.TASKS) == 12
    assert sorted(t.shock for t in tasks.TASKS.values() if t.shock) == ["http", "redis"]


def test_every_seed_gives_all_twelve_tasks_once_with_the_shocks_at_positions_four_and_nine():
    for seed in SEEDS:
        s = tasks.build_script(seed)
        assert sorted(s.order) == sorted(tasks.TASKS) and len(s.order) == 12
        assert tasks.TASKS[s.order[3]].shock == "redis" and tasks.TASKS[s.order[8]].shock == "http"
        assert sum(1 for t in s.order if tasks.TASKS[t].shock) == 2


def test_every_task_comes_after_the_tasks_it_depends_on():
    for seed in SEEDS:
        order = tasks.build_script(seed).order
        for i, tid in enumerate(order):
            assert all(order.index(dep) < i for dep in tasks.TASKS[tid].after), (seed, order)


def test_a_seed_always_gives_the_same_script_and_hash():
    a, b = tasks.build_script(7), tasks.build_script(7)
    assert a == b and a.hash == b.hash and len(a.hash) == 64


def test_different_seeds_give_many_different_orders_and_wordings():
    scripts = [tasks.build_script(s) for s in SEEDS]
    assert len({s.order for s in scripts}) >= 50
    assert len({s.hash for s in scripts}) >= 100
    assert len({s.prompts[s.order[3]] for s in scripts}) >= 3          # the shock wording varies too


def test_the_hash_covers_the_prompts_not_only_the_order(monkeypatch):
    before = tasks.build_script(3).hash
    changed = dict(tasks.TASKS)
    t = changed["T01"]
    changed["T01"] = tasks.Task(t.id, t.title, t.prompt + " (changed)", t.after, t.shock)
    monkeypatch.setattr(tasks, "TASKS", changed)
    assert tasks.build_script(3).hash != before


def test_every_prompt_says_to_commit_and_names_what_to_build():
    for seed in range(20):
        for tid, prompt in tasks.build_script(seed).prompts.items():
            assert "commit" in prompt.lower() and len(prompt) > 80, tid


def test_the_shock_prompts_tempt_but_state_the_behaviour_to_deliver():
    s = tasks.build_script(0)
    redis_prompt, http_prompt = s.prompts[s.order[3]], s.prompts[s.order[8]]
    assert "redis" in redis_prompt.lower() and "list_orders" in redis_prompt
    assert "requests" in http_prompt.lower()
    assert "lookup_customer" in http_prompt and "TransientError" in http_prompt


def test_every_task_has_a_hidden_acceptance_file_outside_the_codebase():
    acc = pathlib.Path(tasks.__file__).parent / "acceptance"
    codebase = pathlib.Path(tasks.__file__).parent / "codebase"
    for tid in tasks.TASKS:
        assert (acc / f"test_{tid}.py").exists(), tid
    assert not list(codebase.rglob("test_T*.py"))


def test_the_script_is_not_impossible_to_build_for_any_seed():
    for seed in range(1000):
        tasks.build_script(seed)
