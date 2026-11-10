"""Helpers for the exploratory Granite-sensitivity diagnostics (REPORT 7.7, "Diagnostics")."""
import numpy as np
import pytest

from benchmarks import diagnostics as diag
from guidancegrid.core.grid import STEER_SIGNAL, SignalPack

torch = pytest.importorskip("torch")
BAND = (1, 4)


def _pack(dim=64, band=BAND, seed=12345):       # an unrelated seed, so a control with seed 0 cannot collide
    rng = np.random.default_rng(seed)
    p = SignalPack("m", dim)
    for layer in range(*band):
        v = rng.standard_normal(dim).astype(np.float32)
        p.set_vector(STEER_SIGNAL, layer, v / np.linalg.norm(v) * (5.0 + layer))
    return p


# -- the random-direction control ----------------------------------------------------------------
def test_a_random_pack_keeps_every_layers_norm_but_not_its_direction():
    pack = _pack()
    rnd = diag.random_direction_pack(pack, BAND, seed=0)
    for layer in range(*BAND):
        a, b = np.asarray(pack.get(STEER_SIGNAL, layer)), np.asarray(rnd.get(STEER_SIGNAL, layer))
        assert b.shape == a.shape and b.dtype == np.float32
        assert np.linalg.norm(b) == pytest.approx(np.linalg.norm(a), rel=1e-5)
        cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
        assert abs(cos) < 0.6                                   # 64-d: a random direction is near-orthogonal


def test_a_random_pack_is_deterministic_per_seed_and_differs_between_seeds():
    pack = _pack()
    a1, a2 = diag.random_direction_pack(pack, BAND, 0), diag.random_direction_pack(pack, BAND, 0)
    b = diag.random_direction_pack(pack, BAND, 1)
    assert a1.hash() == a2.hash() and a1.hash() != b.hash() and a1.hash() != pack.hash()


def test_a_random_pack_covers_only_the_band():
    rnd = diag.random_direction_pack(_pack(band=(0, 6)), BAND, 0)
    assert [layer for layer in range(6) if rnd.get(STEER_SIGNAL, layer) is not None] == [1, 2, 3]


# -- write size -------------------------------------------------------------------------------------
def test_the_write_ratio_per_token_is_the_norm_of_the_change_over_the_norm_of_the_input():
    inp = np.array([[3.0, 4.0], [0.0, 5.0], [6.0, 8.0]])
    out = inp + np.array([[0.0, 0.5], [0.0, 1.0], [0.0, 2.0]])
    assert diag.token_write_ratios(inp, out) == pytest.approx([0.1, 0.2, 0.2])


def test_the_median_over_tokens_is_robust_to_one_huge_token():
    inp = np.array([[1.0, 0.0]] * 5)
    out = inp + np.array([[0.1, 0], [0.1, 0], [0.1, 0], [0.1, 0], [100.0, 0]])   # one huge outlier token
    assert np.median(diag.token_write_ratios(inp, out)) == pytest.approx(0.1)


def _tiny():
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=5,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=128)
    return Qwen2ForCausalLM(cfg).eval()


def test_layer_write_ratios_gives_one_positive_value_per_layer_and_leaves_no_hooks():
    pytest.importorskip("transformers")
    model = _tiny()
    ids = torch.arange(1, 17).unsqueeze(0)
    stats = diag.layer_write_stats(model, ids)
    assert sorted(stats) == [0, 1, 2, 3, 4]
    assert all(s["median_write_ratio"] > 0 and s["median_input_norm"] > 0 for s in stats.values())
    assert sum(len(layer._forward_hooks) + len(layer._forward_pre_hooks) for layer in model.model.layers) == 0
    again = diag.layer_write_stats(model, ids)
    assert again[2] == stats[2]                                                    # deterministic


def test_skipping_the_first_token_changes_the_statistic_but_not_the_layer_set():
    pytest.importorskip("transformers")
    model = _tiny()
    ids = torch.arange(1, 17).unsqueeze(0)
    a, b = diag.layer_write_stats(model, ids), diag.layer_write_stats(model, ids, skip_first=True)
    assert sorted(a) == sorted(b)


# -- push versus write ------------------------------------------------------------------------------
def test_push_to_write_is_the_relative_push_of_the_steering_over_what_the_layer_normally_writes():
    # band (1, 4) of 6 layers: the gaussian envelope is 1.0 at the centre layer 2.0 (between 1 and 3)
    stats = {l: {"median_write_ratio": 0.05, "median_input_norm": 10.0} for l in range(6)}
    pack_norms = {1: 10.0, 2: 10.0, 3: 10.0}
    out = diag.push_to_write(0.025, (1, 4), 6, pack_norms, stats)
    env = diag.envelope((1, 4), 6)
    for layer in (1, 2, 3):
        assert out[layer] == pytest.approx(0.025 * env[layer] * (10.0 / 10.0) / 0.05)
    assert sorted(out) == [1, 2, 3]


def test_push_to_write_grows_with_gain_and_shrinks_when_a_layer_writes_more():
    stats = {l: {"median_write_ratio": 0.05, "median_input_norm": 10.0} for l in range(6)}
    pn = {1: 10.0, 2: 10.0, 3: 10.0}
    low = diag.push_to_write(0.025, (1, 4), 6, pn, stats)
    high = diag.push_to_write(0.05, (1, 4), 6, pn, stats)
    assert high[2] == pytest.approx(2 * low[2])
    big = {l: {"median_write_ratio": 0.10, "median_input_norm": 10.0} for l in range(6)}
    assert diag.push_to_write(0.05, (1, 4), 6, pn, big)[2] == pytest.approx(high[2] / 2)


def test_the_layer_cosine_screen_reports_the_largest_absolute_cosine_over_the_band():
    a, b = _pack(seed=1), _pack(seed=2)
    c = diag.max_abs_layer_cosine(a, b, BAND)
    cosines = []
    for layer in range(*BAND):
        x, y = a.get(STEER_SIGNAL, layer), b.get(STEER_SIGNAL, layer)
        cosines.append(abs(float(np.dot(x, y) / np.linalg.norm(x) / np.linalg.norm(y))))
    manual = max(cosines)
    assert c == pytest.approx(manual)
    assert diag.max_abs_layer_cosine(a, a, BAND) == pytest.approx(1.0)


def test_the_layer_cosine_screen_ignores_the_sign():
    a = _pack(seed=1)
    flipped = SignalPack("m", a.d)
    for layer in range(*BAND):
        flipped.set_vector(STEER_SIGNAL, layer, -np.asarray(a.get(STEER_SIGNAL, layer)))
    assert diag.max_abs_layer_cosine(a, flipped, BAND) == pytest.approx(1.0)
