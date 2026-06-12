"""Linear probe sensor: training, scoring, ProbeMeasure, gaps."""
import numpy as np

from guidancegrid.sensors import LinearProbe, MeasureRegistry, ProbeMeasure


def _separable(seed=0, d=16, n=64):
    rng = np.random.default_rng(seed)
    pos = rng.standard_normal((n, d)) + np.r_[np.ones(4), np.zeros(d - 4)]
    neg = rng.standard_normal((n, d)) - np.r_[np.ones(4), np.zeros(d - 4)]
    return pos, neg


def test_probe_trains_and_separates():
    pos, neg = _separable()
    p = LinearProbe.train(layer=12, pos=pos, neg=neg)
    assert p.score(pos.mean(0)) > 0.5            # adherent side
    assert p.score(neg.mean(0)) < 0.5            # non-adherent side
    assert 0.0 <= p.score(np.zeros(16)) <= 1.0   # bounded


def test_probe_roundtrip():
    pos, neg = _separable()
    p = LinearProbe.train(layer=5, pos=pos, neg=neg)
    p2 = LinearProbe.from_dict(p.to_dict())
    x = pos[0]
    assert abs(p.score(x) - p2.score(x)) < 1e-6
    assert p2.layer == 5


def test_probe_measure_reads_residual():
    pos, neg = _separable()
    p = LinearProbe.train(layer=3, pos=pos, neg=neg)
    m = ProbeMeasure("probe:adherence_to_user", p)
    r = m.read({"residual": {3: pos.mean(0)}})
    assert r.value is not None and r.value > 0.5
    assert r.determinism == "deterministic"


def test_probe_measure_missing_residual_is_gap():
    pos, neg = _separable()
    p = LinearProbe.train(layer=3, pos=pos, neg=neg)
    m = ProbeMeasure("probe:adherence_to_user", p)
    assert m.read({}).is_gap                      # no residual on ctx
    assert m.read({"residual": {0: pos.mean(0)}}).is_gap   # wrong layer


def test_probe_measure_in_registry():
    pos, neg = _separable()
    reg = MeasureRegistry()
    reg.register(ProbeMeasure("probe:adherence", LinearProbe.train(7, pos, neg)))
    r = reg.read("probe:adherence", {"residual": {7: pos.mean(0)}})
    assert r.value > 0.5
