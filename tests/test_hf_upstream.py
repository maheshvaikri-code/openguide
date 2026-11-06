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

