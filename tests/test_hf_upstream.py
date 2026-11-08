"""HFUpstream: an in-process local-model Upstream. Tested with an injected generator (no weights)."""
import asyncio
import json

from proxy.hf_upstream import HFUpstream
from proxy.streaming import StreamAssembler


def _up(reply="hello there [END]", calls=None):
    def gen(messages, max_new_tokens):
        if calls is not None:
            calls.append((messages, max_new_tokens))
        return reply, 11, 5
    return HFUpstream(generate_fn=gen, served_name="local:test-model")


def test_chat_returns_an_openai_completion():
    out = asyncio.run(_up().chat({"model": "local:x", "messages": [{"role": "user", "content": "hi"}]}, {}))
    assert out["object"] == "chat.completion"
    assert out["choices"][0]["message"] == {"role": "assistant", "content": "hello there [END]"}
    assert out["choices"][0]["finish_reason"] == "stop"
    assert out["usage"] == {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16}
    assert out["model"] == "local:x"                         # echoes what the caller asked for


def test_messages_and_max_tokens_reach_the_generator():
    calls = []
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    asyncio.run(_up(calls=calls).chat({"messages": msgs, "max_tokens": 33}, {}))
    assert calls == [(msgs, 33)]


def test_max_tokens_is_capped_and_defaulted():
    calls = []
    up = HFUpstream(generate_fn=lambda m, n: (calls.append(n) or ("x", 1, 1)), max_new_tokens=64)
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "a"}]}, {}))
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "a"}], "max_tokens": 10_000}, {}))
    assert calls == [64, 64]                                  # default, then capped at the configured ceiling


def test_stream_reassembles_to_the_same_text_and_ends_with_done():
    async def collect():
        return [c async for c in _up("plain text answer [END]").stream(
            {"messages": [{"role": "user", "content": "q"}]}, {})]

    chunks = asyncio.run(collect())
    assert chunks[-1] == b"data: [DONE]\n\n"
    asm = StreamAssembler()
    for c in chunks:
        asm.feed_bytes(c)
    assert asm.message()["content"] == "plain text answer [END]"
    for c in chunks[:-1]:
        assert json.loads(c.decode().removeprefix("data: "))["object"] == "chat.completion.chunk"


def test_non_text_message_content_is_flattened():
    calls = []
    parts = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    asyncio.run(_up(calls=calls).chat({"messages": [{"role": "user", "content": parts}]}, {}))
    assert calls[0][0] == [{"role": "user", "content": "ab"}]


def test_an_empty_conversation_is_rejected_clearly():
    import pytest

    with pytest.raises(ValueError, match="messages"):
        asyncio.run(_up().chat({"messages": []}, {}))


def test_generation_is_serialised_so_two_requests_never_share_the_gpu():
    import threading
    import time

    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def gen(messages, n):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        with lock:
            active["now"] -= 1
        return "x", 1, 1

    up = HFUpstream(generate_fn=gen)

    async def both():
        body = {"messages": [{"role": "user", "content": "a"}]}
        await asyncio.gather(up.chat(body, {}), up.chat(body, {}))

    asyncio.run(both())
    assert active["max"] == 1


def test_around_context_wraps_every_generation_inside_the_lock():
    from contextlib import contextmanager

    events = []

    @contextmanager
    def around():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def gen(messages, n):
        events.append("generate")
        return "x", 1, 1

    up = HFUpstream(generate_fn=gen)
    up.around = around
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "a"}]}, {}))
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "a"}]}, {}))
    assert events == ["enter", "generate", "exit"] * 2


def test_around_is_exited_even_when_generation_fails():
    from contextlib import contextmanager

    state = {"open": False}

    @contextmanager
    def around():
        state["open"] = True
        try:
            yield
        finally:
            state["open"] = False

    def boom(messages, n):
        raise RuntimeError("cuda said no")

    up = HFUpstream(generate_fn=boom)
    up.around = around
    import pytest

    with pytest.raises(RuntimeError, match="cuda said no"):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "a"}]}, {}))
    # a hook left registered would poison every later call
    assert state["open"] is False



# ── steering (ADR-003) ────────────────────────────────────────────────
def _steerable(events):
    from contextlib import contextmanager

    up = _up()

    @contextmanager
    def factory(gain):
        events.append(("enter", gain))
        try:
            yield
        finally:
            events.append(("exit", gain))

    up.steer_factory = factory
    return up


def test_an_upstream_without_a_steering_hook_does_not_claim_to_support_it():
    assert _up().supports_steering is False
    assert _steerable([]).supports_steering is True


def test_steering_is_entered_around_the_generation_and_left_after_it():
    events = []
    up = _steerable(events)
    gen = up._generate
    up._generate = lambda m, n: (events.append(("generate", None)) or gen(m, n))
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05))
    assert events == [("enter", 0.05), ("generate", None), ("exit", 0.05)]


def test_no_steering_is_entered_when_not_asked_for():
    events = []
    asyncio.run(_steerable(events).chat({"messages": [{"role": "user", "content": "hi"}]}, {}))
    assert events == []


def test_asking_to_steer_an_upstream_that_cannot_is_an_error_not_a_silent_skip():
    import pytest

    with pytest.raises(ValueError, match="steer"):
        asyncio.run(_up().chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05))


def test_the_steering_hook_is_left_even_when_generation_fails():
    import pytest

    events = []
    up = _steerable(events)

    def boom(messages, n):
        raise RuntimeError("out of memory")

    up._generate = boom
    with pytest.raises(RuntimeError):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05))
    assert events == [("enter", 0.05), ("exit", 0.05)]


def test_a_streamed_reply_can_be_steered_too():
    events = []
    up = _steerable(events)

    async def collect():
        return [c async for c in up.stream({"messages": [{"role": "user", "content": "q"}]}, {}, steer=0.05)]

    asyncio.run(collect())
    assert events == [("enter", 0.05), ("exit", 0.05)]


def test_enable_steering_checks_the_pack_against_the_model_and_hooks_only_while_generating():
    import numpy as np
    import pytest

    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import Qwen2Config, Qwen2ForCausalLM

    from guidancegrid.core.grid import STEER_SIGNAL, SignalPack

    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=6,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=64)
    model = Qwen2ForCausalLM(cfg).eval()

    def pack(dim):
        p = SignalPack("tiny", dim)
        for layer in (1, 2, 3):
            p.set_vector(STEER_SIGNAL, layer, np.ones(dim, dtype=np.float32))
        return p

    def hooks():
        return sum(len(layer._forward_hooks) for layer in model.model.layers)

    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1))
    with pytest.raises(ValueError, match="model"):                       # needs the model itself
        up.enable_steering(_exp(pack(32), (1, 4)))
    up.model = model
    with pytest.raises(ValueError, match="hidden size"):                 # a pack for another model
        up.enable_steering(_exp(pack(16), (1, 4)))
    with pytest.raises(ValueError, match="layers"):                      # band reaches past the last layer
        up.enable_steering(_exp(_wide_pack(32, 9), (1, 9)))
    assert up.enable_steering(_exp(_scaled_pack(model, 1.0), (1, 4))) is up
    assert up.supports_steering and hooks() == 0  # nothing hooked until steered
    with up.steer_factory(0.05):
        assert hooks() == 6
    assert hooks() == 0


def _wide_pack(dim, hi):
    import numpy as np

    from guidancegrid.core.grid import STEER_SIGNAL, SignalPack

    p = SignalPack("tiny", dim)
    for layer in range(1, hi):
        p.set_vector(STEER_SIGNAL, layer, np.ones(dim, dtype=np.float32))
    return p


def _tiny_model():
    import pytest

    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(0)
    cfg = Qwen2Config(vocab_size=64, hidden_size=32, intermediate_size=64, num_hidden_layers=6,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=2048)
    return Qwen2ForCausalLM(cfg).eval()


def _scaled_pack(model, scale):
    """A pack whose vector at every band layer is `scale` times the model's typical residual norm there."""
    import numpy as np
    import torch

    from guidancegrid.core.grid import STEER_SIGNAL, SignalPack

    ids = torch.arange(1, 33).unsqueeze(0)
    with torch.no_grad():
        hs = model(input_ids=ids, output_hidden_states=True).hidden_states
    pack = SignalPack("tiny", 32)
    for layer in (1, 2, 3):
        typical = float(hs[layer + 1][0].norm(dim=-1).median())
        v = np.ones(32, dtype=np.float32)
        pack.set_vector(STEER_SIGNAL, layer, v / np.linalg.norm(v) * typical * scale)
    return pack


def test_enable_steering_accepts_a_pack_at_the_models_own_scale_and_refuses_one_that_would_overwrite_it():
    import pytest


    model = _tiny_model()
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=64)
    up.model = model
    up.enable_steering(_exp(_scaled_pack(model, 1.0), (1, 4)))      # what derive makes
    with pytest.raises(ValueError, match="norm"):
        up.enable_steering(_exp(_scaled_pack(model, 1e6), (1, 4)))   # swamps the state
    with pytest.raises(ValueError, match="norm"):
        up.enable_steering(_exp(_scaled_pack(model, 50.0), (1, 4)))


def test_enable_steering_refuses_a_reply_length_longer_than_the_steering_field_covers():
    import pytest


    model = _tiny_model()
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=5000)
    up.model = model
    with pytest.raises(ValueError, match="max_new_tokens"):
        up.enable_steering(_exp(_scaled_pack(model, 1.0), (1, 4)))


def test_the_gain_ceiling_is_enforced_at_the_upstream_too():
    import pytest

    up = _steerable([])
    with pytest.raises(ValueError, match="gain"):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=5.0))


def test_the_upstream_reports_a_steered_reply_through_the_receipt_only_once_it_exists():
    import pytest

    from proxy.steering import SteerReceipt

    up = _steerable([])
    receipt = SteerReceipt(0.05)
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05, receipt=receipt))
    assert receipt.produced is True

    failing = _steerable([])

    def oom(messages, n):
        raise RuntimeError("oom")

    failing._generate = oom
    receipt2 = SteerReceipt(0.05)
    with pytest.raises(RuntimeError):
        asyncio.run(failing.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05,
                                 receipt=receipt2))
    assert receipt2.produced is False

    untouched = SteerReceipt(0.05)
    asyncio.run(_steerable([]).chat({"messages": [{"role": "user", "content": "hi"}]}, {}, receipt=untouched))
    assert untouched.produced is False                              # not steered, so nothing to report


def test_enable_steering_steers_only_the_bands_layers_even_if_the_pack_has_more():
    import numpy as np
    import pytest

    torch = pytest.importorskip("torch")
    from guidancegrid.core.grid import STEER_SIGNAL

    model = _tiny_model()
    wide = _scaled_pack(model, 1.0)                                   # layers 1..3
    for layer in (0, 4, 5):                                           # extra layers, same scale
        wide.set_vector(STEER_SIGNAL, layer, np.asarray(wide.get(STEER_SIGNAL, 2)))
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=64)
    up.model = model
    up.enable_steering(_exp(wide, (2, 4)))
    with up.steer_factory(0.05) as steerer:
        with torch.no_grad():
            model(input_ids=torch.arange(1, 9).unsqueeze(0))
    layers = {layer for rec in steerer.trace.records if rec.get("ev") == "STEP"
              for layer, _ in rec["applied"].get(STEER_SIGNAL, [])}
    assert layers and layers <= {2, 3}


def test_the_upstream_enforces_the_configured_ceiling_not_just_the_default():
    import pytest


    model = _tiny_model()
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=64)
    up.model = model
    up.enable_steering(_exp(_scaled_pack(model, 1.0), (1, 4), gain=0.075, ceiling=0.075))
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.075))     # at it
    with pytest.raises(ValueError, match="gain"):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.08))


def test_the_dtype_option_resolves_names_and_defaults_are_unchanged():
    import pytest

    torch = pytest.importorskip("torch")
    from proxy.hf_upstream import _resolve_dtype

    assert _resolve_dtype(None, "cuda") is torch.float16              # the default every earlier result used
    assert _resolve_dtype(None, "cpu") is torch.float32
    assert _resolve_dtype("bfloat16", "cuda") is torch.bfloat16
    assert _resolve_dtype("float32", "cuda") is torch.float32
    with pytest.raises(ValueError, match="dtype"):
        _resolve_dtype("int4", "cuda")



def _exp(pack, band, gain=0.05, ceiling=0.05):
    """A tiny random model has no validation record, so these tests are experiments by definition."""
    from proxy.steering import SteeringConfig

    return SteeringConfig(pack, band, gain, experimental=True, gain_ceiling=ceiling)


# -- steering fails closed on a model with no record (ADR-003, REPORT 7.7) -------------------------
def _weights_dir(tmp_path, data=b"tiny"):
    d = tmp_path / "weights"
    d.mkdir(exist_ok=True)
    (d / "model.safetensors").write_bytes(data)
    return str(d)


def _validated_upstream(tmp_path, records_for=None):
    from proxy import validation as val

    model = _tiny_model()
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=64)
    up.model = model
    up.weights_path = _weights_dir(tmp_path)
    pack = _scaled_pack(model, 1.0)
    rec = val.ValidationRecord(key="tiny", weights_sha256=val.weights_identity(up.weights_path), band=(1, 4),
                               gain_ceiling=0.04, pack_hash=pack.hash(), evidence=(("r.json", "abc1234"),))
    return up, pack, {rec.weights_sha256: rec}


def test_a_model_with_no_record_cannot_be_steered_and_nothing_is_hooked(tmp_path):
    import pytest

    from proxy import validation as val
    from proxy.steering import SteeringConfig

    model = _tiny_model()
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=64)
    up.model = model
    up.weights_path = _weights_dir(tmp_path)
    with pytest.raises(val.NotValidated, match="no validation record"):
        up.enable_steering(SteeringConfig(_scaled_pack(model, 1.0), (1, 4), 0.025), records={})
    assert up.supports_steering is False and up.steer_factory is None


def test_a_validated_model_is_steerable_within_its_recorded_ceiling_and_no_further(tmp_path):
    import pytest

    from proxy.steering import SteeringConfig

    up, pack, records = _validated_upstream(tmp_path)
    up.enable_steering(SteeringConfig(pack, (1, 4), 0.03), records=records)
    assert up.supports_steering
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.04))   # at the ceiling
    with pytest.raises(ValueError, match="gain"):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.05))


def test_the_experimental_override_works_without_a_record_and_sets_its_own_ceiling(tmp_path):
    import pytest

    model = _tiny_model()
    up = HFUpstream(generate_fn=lambda m, n: ("x", 1, 1), max_new_tokens=64)
    up.model = model
    up.enable_steering(_exp(_scaled_pack(model, 1.0), (1, 4), gain=0.025, ceiling=0.06), records={})
    asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.06))
    with pytest.raises(ValueError, match="gain"):
        asyncio.run(up.chat({"messages": [{"role": "user", "content": "hi"}]}, {}, steer=0.07))


def test_from_pretrained_records_where_the_weights_are():
    import inspect

    assert "weights_path" in inspect.getsource(HFUpstream.from_pretrained)
