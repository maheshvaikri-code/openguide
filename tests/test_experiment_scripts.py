"""The experiment scripts must at least import: a removed default once left one of them unable to start."""
import importlib

import pytest

pytest.importorskip("torch")

SCRIPTS = [
    "scripts.real_closed_loop", "scripts.replicate_t0", "scripts.replicate_cap", "scripts.replicate_pool2",
    "scripts.pilot_second_model", "scripts.derive_steering_pack", "scripts.real_t0_gate",
    "scripts.replicate_direction_control", "scripts.replicate_direction_draws", "scripts.granite_gain_ladder",
    "scripts.diagnose_granite_sensitivity",
]


@pytest.mark.parametrize("name", SCRIPTS)
def test_the_experiment_script_imports(name):
    importlib.import_module(name)


def test_every_script_that_generates_in_batches_sets_left_padding():
    """Right-padded batches answer differently; a runner once forgot and its baseline stopped reproducing."""
    import pathlib

    missing = []
    for path in sorted(pathlib.Path("scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "generate_batch(" in text and 'padding_side = "left"' not in text:
            missing.append(path.name)
    assert not missing, f"batched generation without left padding in: {missing}"


def test_the_draw_summary_counts_marked_records_and_the_worst_paired_differences():
    from scripts.replicate_direction_draws import draw_summary

    def conv(seed, ok, steered=(), marks=0):
        turns = [{"turn": i, "kind": "tempting" if i == 4 else "plain", "ok": ok, "reply": "fine"}
                 for i in range(16)]
        return {"seed": seed, "turns": turns, "steered_turns": list(steered), "experimental_marks": marks}

    rules = [conv(1, True), conv(2, True)]
    t2 = [conv(1, False), conv(2, True)]
    draw = [conv(1, False, steered=(5, 6), marks=2), conv(2, True, steered=(7,), marks=1)]
    s = draw_summary(rules, t2, draw)
    assert s["steer_records"] == 3 and s["marked_experimental"] == 3
    assert s["worst_rules_minus_random"] == 0.0      # conversation 2: rules and the draw both recover fully
    assert s["worst_random_minus_t2"] == 0.0 and s["mean_recovery"] == 0.5
    assert s["replies"] == 32 and s["not_english_replies"] == 0
