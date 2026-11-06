"""Real T0 steering helpers, tested on a tiny randomly initialised Qwen2 (CPU, no weights, no network)."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from benchmarks import real_t0 as t0  # noqa: E402
from guidancegrid.core.grid import SignalPack  # noqa: E402


@pytest.fixture(scope="module")
def tiny():
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=6,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=128)
    return Qwen2ForCausalLM(cfg).eval()


def _batch(n=4, length=9, seed=1):
    g = torch.Generator().manual_seed(seed)
    ids = torch.randint(1, 60, (n, length), generator=g)
    return ids, torch.ones_like(ids)


BAND = (1, 4)


# ── deriving vectors ──────────────────────────────────────────────────
def test_last_token_states_has_one_row_per_example_for_each_requested_layer(tiny):
    ids, mask = _batch(4)
    states = t0.last_token_states(tiny, ids, mask, [1, 2, 3])
    assert set(states) == {1, 2, 3}
    for arr in states.values():
        assert arr.shape == (4, 32) and arr.dtype == np.float32


def test_build_pack_points_along_the_mean_difference_at_the_typical_norm():
    rng = np.random.default_rng(0)
    direction = rng.standard_normal(16)
    direction /= np.linalg.norm(direction)
    base = rng.standard_normal((20, 16)).astype(np.float32)
    with_rules = base + 3.0 * direction.astype(np.float32)
    pack = t0.build_pack("m", {2: with_rules}, {2: base})
    v = np.asarray(pack.get(t0.SIGNAL, 2))
    cos = float(v @ direction / np.linalg.norm(v))
    assert cos > 0.95                                               # points where the data differ
    typical = float(np.linalg.norm(np.concatenate([with_rules, base]), axis=1).mean())
    # gain 1.0 means one typical residual norm
    assert float(np.linalg.norm(v)) == pytest.approx(typical, rel=1e-4)


def test_build_pack_skips_layers_where_the_conditions_are_identical():
    same = np.ones((5, 8), dtype=np.float32)
    pack = t0.build_pack("m", {1: same}, {1: same})
    assert pack.get(t0.SIGNAL, 1) is None                           # no direction to steer along


def test_build_pack_rejects_mismatched_layer_sets():
    a = np.ones((2, 8), dtype=np.float32)
    with pytest.raises(ValueError, match="layers"):
        t0.build_pack("m", {1: a}, {2: a})


# ── applying steering ─────────────────────────────────────────────────
def _pack_for(tiny, seed=3):
    ids, mask = _batch(6, seed=seed)
    ids2, mask2 = _batch(6, seed=seed + 1)
    layers = list(range(*BAND))
    return t0.build_pack("tiny", t0.last_token_states(tiny, ids, mask, layers),
                         t0.last_token_states(tiny, ids2, mask2, layers))


def _logits(model, ctx=None):
    ids, mask = _batch(2, seed=9)
    from contextlib import nullcontext
    with torch.no_grad(), (ctx() if ctx else nullcontext()):
        return model(input_ids=ids, attention_mask=mask).logits


def test_gain_zero_changes_nothing_and_registers_no_hooks(tiny):
    pack = _pack_for(tiny)
    base = _logits(tiny)
    ctx = t0.steering_context(tiny, pack, BAND, 0.0, {"model": "tiny"})
    with ctx() as s:
        assert s is None
        assert all(len(m._forward_hooks) == 0 for m in t0.decoder_layers(tiny))
    assert torch.equal(base, _logits(tiny, ctx))


def test_positive_gain_moves_the_logits_and_hooks_are_removed_afterwards(tiny):
    pack = _pack_for(tiny)
    base = _logits(tiny)
    ctx = t0.steering_context(tiny, pack, BAND, 0.6, {"model": "tiny"})
    steered = _logits(tiny, ctx)
    assert not torch.allclose(base, steered, atol=1e-5)
    assert all(len(m._forward_hooks) == 0 for m in t0.decoder_layers(tiny))   # nothing left behind
    assert torch.equal(base, _logits(tiny))                                    # the model is back to normal


def test_hooks_are_removed_even_if_the_body_raises(tiny):
    pack = _pack_for(tiny)
    ctx = t0.steering_context(tiny, pack, BAND, 0.4, {"model": "tiny"})
    with pytest.raises(RuntimeError):
        with ctx():
            raise RuntimeError("generation failed")
    assert all(len(m._forward_hooks) == 0 for m in t0.decoder_layers(tiny))


def test_a_larger_gain_moves_the_logits_further(tiny):
    pack = _pack_for(tiny)
    base = _logits(tiny)
    d = {g: float((_logits(tiny, t0.steering_context(tiny, pack, BAND, g, {"m": 1})) - base).abs().mean())
         for g in (0.2, 0.6)}
    assert 0 < d[0.2] < d[0.6]


def test_steering_is_deterministic_and_its_trace_replays_bit_identically(tiny):
    pack = _pack_for(tiny)
    runs = []
    for _ in range(2):
        ctx = t0.steering_context(tiny, pack, BAND, 0.4, {"model": "tiny", "pack_hash": pack.hash()})
        with ctx() as s:
            ids, mask = _batch(2, seed=9)
            with torch.no_grad():
                tiny(input_ids=ids, attention_mask=mask)
            runs.append((s.trace.head, s.trace.verify(), len(s.trace.records)))
    assert runs[0] == runs[1]
    assert runs[0][1] is True and runs[0][2] > 0                  # a verified chain with real step records


def test_the_pack_is_a_signalpack_with_vectors_only_inside_the_band(tiny):
    pack = _pack_for(tiny)
    assert isinstance(pack, SignalPack)
    present = [layer for layer in range(6) if pack.get(t0.SIGNAL, layer) is not None]
    assert present == list(range(*BAND))


# ── evaluators ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("so the total is 42. The answer is 42", "42"),
    ("The answer is $1,234.", "1234"),
    ("First 5 then 7, so 12 apples", "12"),
    ("The answer is -3", "-3"),
    ("The answer is 3.50", "3.5"),
    ("no numbers here", None),
    ("", None),
])
def test_extract_number(text, expected):
    assert t0.extract_number(text) == expected


def test_gsm8k_gold_is_the_number_after_the_hashes():
    assert t0.gsm8k_gold("some working <<1+1=2>> #### 1,008") == "1008"
    assert t0.gsm8k_gold("#### 72") == "72"


def test_numbers_compare_by_value_not_spelling():
    assert t0.same_number("3.50", "3.5") and t0.same_number("1008", "1,008") and not t0.same_number("3", "4")
    assert not t0.same_number(None, "4")


def test_mmlu_prompt_lists_four_lettered_options():
    p = t0.mmlu_prompt("What is 2+2?", ["3", "4", "5", "6"])
    for line in ("A. 3", "B. 4", "C. 5", "D. 6"):
        assert line in p
    assert p.rstrip().endswith("letter")


def test_compliance_rates_use_the_real_rule_checker():
    r = t0.compliance(["ok [END]", "**bold**", "plain"])
    assert r["n"] == 3 and r["all"] == pytest.approx(1 / 3)
    assert r["sign_off"] == pytest.approx(1 / 3) and r["plain_text"] == pytest.approx(2 / 3)
    assert t0.compliance([])["all"] is None


def test_wilson_interval_is_sane():
    lo, hi = t0.wilson(7, 10)
    assert 0.39 < lo < 0.40 and 0.89 < hi < 0.90
    assert t0.wilson(0, 0) == (None, None)
    lo, hi = t0.wilson(10, 10)
    assert hi == pytest.approx(1.0) and lo < 1.0
