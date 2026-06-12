import numpy as np
import pytest

from guidancegrid import (
    GainField, Grid, SignalPack, GridRuntime, Trace,
    compile_spec, spec_hash, inject, grid_tune, constant_baseline, simulate, chash,
)

L, W, D = 32, 16, 64


# ── totality ──────────────────────────────────────────────────────────

def test_totality_unset_cells_are_zero():
    f = GainField(L, W)
    assert f.get(0, 0) == 0.0
    assert f.get(31, 99999) == 0.0           # any coordinate answers
    assert not f.column(12345).any()

def test_out_of_lattice_raises():
    f = GainField(L, W)
    with pytest.raises(IndexError):
        f.get(L, 0)
    with pytest.raises(IndexError):
        f.get(0, -1)

def test_write_read_roundtrip():
    f = GainField(L, W)
    f.paint(10, 10, 33, 33, lambda l, t: 0.5)
    assert f.get(10, 33) == pytest.approx(0.5)
    assert f.get(10, 32) == 0.0
    assert f.get(11, 33) == 0.0


# ── schedules ─────────────────────────────────────────────────────────

def test_ramp_monotone_at_center():
    f = GainField(L, W)
    f.write_ramp(12, 24, 0, 99, 0.0, 0.6)
    c = 18
    vals = [f.get(c, t) for t in (0, 30, 60, 99)]
    assert vals == sorted(vals)
    assert vals[-1] == pytest.approx(0.6, abs=0.02)

def test_decay_halves_at_tau_ln2():
    f = GainField(L, W)
    f.write_decay(20, 30, 40, 0.8, tau=8, horizon=40)
    c = 25
    g0 = f.get(c, 40)
    g_tau = f.get(c, 48)
    assert g_tau / g0 == pytest.approx(np.exp(-1), abs=0.01)


# ── algebra closure ───────────────────────────────────────────────────

def test_add_is_cellwise():
    a, b = GainField(L, W), GainField(L, W)
    a.write_const(10, 14, 0, 50, 0.3)
    b.write_const(12, 20, 20, 80, 0.2)
    s = a + b
    for (l, t) in [(12, 25), (10, 5), (18, 70), (0, 0)]:
        assert s.get(l, t) == pytest.approx(a.get(l, t) + b.get(l, t), abs=1e-6)

def test_scalar_and_mask_and_shift_and_crop():
    f = GainField(L, W)
    f.write_const(8, 16, 10, 40, 0.4)
    g2 = 0.5 * f
    assert g2.get(12, 20) == pytest.approx(f.get(12, 20) * 0.5)
    m = f.mask(8, 16, 10, 20, 0.0)
    assert m.get(12, 15) == 0.0
    assert m.get(12, 30) == pytest.approx(f.get(12, 30))
    sh = f.shift_t(5)
    assert sh.get(12, 25) == pytest.approx(f.get(12, 20))
    cr = f.crop(15, 18)
    assert cr.get(12, 16) == pytest.approx(f.get(12, 16))
    assert cr.get(12, 30) == 0.0

def test_grid_compose():
    g1, g2 = Grid(L, W), Grid(L, W)
    g1.field("anchor").write_const(12, 24, 0, 50, 0.3)
    g2.field("anchor").write_const(12, 24, 0, 50, 0.2)
    g2.field("damp").write_const(14, 22, 0, 50, 0.1)
    g3 = g1.compose(g2, alpha=0.5)
    c = 18
    assert g3.field("anchor").get(c, 25) == pytest.approx(
        g1.field("anchor").get(c, 25) + 0.5 * g2.field("anchor").get(c, 25))
    assert "damp" in g3.fields


# ── hashing & determinism ─────────────────────────────────────────────

SPEC = {
    "layers": L, "frame": W,
    "signals": {
        "anchor":    {"layers": [12, 24], "schedule": {"type": "ramp", "t": [0, 95], "g": [0.08, 0.55]}},
        "explore":   {"layers": [8, 16],  "schedule": {"type": "window", "t": [0, 20], "g": 0.5}},
        "precision": {"layers": [20, 30], "schedule": {"type": "none"}},
    },
    "triggers": [
        {"on": "tool_call", "apply": {"signal": "precision", "layers": [20, 30], "g": 0.7, "tau": 8}}
    ],
}

def test_spec_hash_deterministic_and_sensitive():
    h1, h2 = spec_hash(SPEC), spec_hash(dict(SPEC))
    assert h1 == h2 and h1.startswith("sha256:")
    mod = {**SPEC, "frame": 8}
    assert spec_hash(mod) != h1

def test_compiled_grid_hash_deterministic():
    assert compile_spec(SPEC).hash() == compile_spec(SPEC).hash()

def test_pack_hash_and_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    pack = SignalPack("toy-model-v1", D)
    pos = rng.standard_normal((8, L, D)) + 0.5
    neg = rng.standard_normal((8, L, D))
    pack.derive_contrast("anchor", pos, neg, range(12, 25))
    h = pack.hash()
    p = tmp_path / "pack.npz"
    pack.save(str(p))
    loaded = SignalPack.load(str(p))
    assert loaded.hash() == h
    assert np.allclose(loaded.get("anchor", 18), pack.get("anchor", 18))


# ── injection physics ─────────────────────────────────────────────────

def test_inject_preserves_norm():
    rng = np.random.default_rng(1)
    h = rng.standard_normal(D).astype(np.float32)
    v = rng.standard_normal(D).astype(np.float32)
    v /= np.linalg.norm(v)
    out = inject(h, v, 0.6)
    assert np.linalg.norm(out) == pytest.approx(np.linalg.norm(h), rel=1e-5)
    assert not np.allclose(out, h)          # direction actually moved


# ── runtime: cap, knobs, triggers, trace ──────────────────────────────

def make_runtime():
    grid = compile_spec(SPEC)
    rng = np.random.default_rng(2)
    pack = SignalPack("toy-model-v1", D)
    for sig, (lo, hi) in [("anchor", (12, 24)), ("explore", (8, 16)), ("precision", (20, 30))]:
        pos = rng.standard_normal((8, L, D)) + 0.4
        neg = rng.standard_normal((8, L, D))
        pack.derive_contrast(sig, pos, neg, range(lo, hi + 1))
    manifest = {"model": pack.model_id, "spec_hash": spec_hash(SPEC), "spec": SPEC,
                "pack_hash": pack.hash(), "seed": 7, "runtime": "ggrid-ref-0.1.0"}
    return GridRuntime(grid, pack, manifest), rng

def test_sigma_cap_enforced():
    rt, rng = make_runtime()
    rt.grid.field("anchor").write_const(12, 24, 50, 50, 5.0)   # absurd overdrive
    h = rng.standard_normal((L, D)).astype(np.float32)
    rt.apply(h, 50)
    rec = rt.trace.records[-1]
    assert rec["sigma_peak"] > rt.sigma_cap
    assert rec["norm_corr"] > 0
    applied = [g for gains in rec["applied"].values() for _, g in gains]
    assert max(abs(g) for g in applied) <= rt.sigma_cap + 1e-4

def test_knob_and_trigger_are_recorded_and_effective():
    rt, rng = make_runtime()
    h = rng.standard_normal((L, D)).astype(np.float32)
    rt.apply(h, 10)
    rt.set_gain("anchor", 0.0, t=11)                # mute live
    out_muted = rt.apply(h, 60)
    rec = rt.trace.records[-1]
    assert "anchor" not in rec["applied"]
    rt.fire("tool_call", t=61)
    rt.apply(h, 61)
    rec = rt.trace.records[-1]
    assert "precision" in rec["applied"]
    evs = [r["ev"] for r in rt.trace.records]
    assert "OVERRIDE" in evs and "TRIGGER" in evs
    assert rt.trace.verify()

def test_trace_tamper_detection():
    rt, rng = make_runtime()
    h = rng.standard_normal((L, D)).astype(np.float32)
    for t in range(5):
        rt.apply(h, t)
    assert rt.trace.verify()
    rt.trace.records[2]["applied"] = {}             # tamper
    assert not rt.trace.verify()

def test_replay_identity_bit_identical_heads():
    def run():
        rt, rng = make_runtime()
        h = rng.standard_normal((L, D)).astype(np.float32)
        for t in range(0, 96):
            if t == 30 or t == 60:
                rt.fire("tool_call", t)
            h = rt.apply(h, t)
        return rt.trace.head, h
    head1, h1 = run()
    head2, h2 = run()
    assert head1 == head2                           # replay key holds
    assert np.allclose(h1, h2)

def test_divergent_grids_divergent_traces():
    rt1, rng1 = make_runtime()
    rt2, rng2 = make_runtime()
    rt2.set_gain("anchor", 0.5, t=0)
    h = np.ones((L, D), dtype=np.float32)
    for t in range(20):
        rt1.apply(h, t)
        rt2.apply(h, t)
    assert rt1.trace.head != rt2.trace.head


# ── grid tuning: the differentiability payoff ─────────────────────────

def test_grid_tuning_converges_and_beats_constant_baseline():
    res = grid_tune()
    # loss decreases substantially
    assert res["losses"][-1] < res["losses"][0] * 0.2
    # setpoint held within tolerance (measurable, not prose)
    assert res["min_adherence"] >= 0.85 - 0.015
    # learned schedule spends far less total gain than the best constant gain
    g_const, a_const = constant_baseline(96, 16, 0.85, res["drift"])
    assert a_const[1:].min() >= 0.85 - 1e-9
    assert res["mean_gain"] < 0.6 * g_const
    # learned profile ramps: late frames out-spend early ones (drift grows late)
    pr = res["params"]
    assert pr[-2:].mean() > 4 * max(pr[:2].mean(), 1e-6)