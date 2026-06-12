"""Sensors: typed measures, determinism tagging, gaps, registry."""
from guidancegrid.sensors import (
    ExternalMeasure,
    JudgeMeasure,
    MeasureRegistry,
    StructuralMeasure,
)


def test_structural_bool_and_clamp():
    m = StructuralMeasure("structural:flag", lambda ctx: ctx["ok"])
    assert m.read({"ok": True}).value == 1.0
    assert m.read({"ok": False}).value == 0.0
    over = StructuralMeasure("structural:big", lambda ctx: 5.0)
    assert over.read({}).value == 1.0           # clamped to [0,1]


def test_structural_regex_constructors():
    absent = StructuralMeasure.regex_absent("structural:no_force", r"force.?push")
    assert absent.read({"output": "git push"}).value == 1.0
    assert absent.read({"output": "git force-push"}).value == 0.0
    present = StructuralMeasure.regex_present("structural:has_tests", r"def test_")
    assert present.read({"output": "def test_x(): ..."}).value == 1.0


def test_measure_failure_becomes_gap():
    def boom(ctx):
        raise RuntimeError("sensor down")
    m = StructuralMeasure("structural:boom", boom)
    r = m.read({})
    assert r.is_gap and r.value is None


def test_determinism_tags():
    s = StructuralMeasure("structural:x", lambda c: 1.0)
    e = ExternalMeasure("external:y", lambda c: 0.5)
    j = JudgeMeasure("judge:z", lambda c: 0.9)
    assert s.read({}).determinism == "deterministic"
    assert e.read({}).determinism == "deterministic" and e.latency_class == "slow"
    assert j.read({}).determinism == "stochastic"


def test_registry_known_and_unknown():
    reg = MeasureRegistry()
    reg.register(StructuralMeasure("structural:ok", lambda c: True))
    assert reg.read("structural:ok", {}).value == 1.0
    # unknown ref -> gap, tagged by kind
    g = reg.read("judge:missing", {})
    assert g.is_gap and g.determinism == "stochastic"
    g2 = reg.read("structural:missing", {})
    assert g2.is_gap and g2.determinism == "deterministic"
