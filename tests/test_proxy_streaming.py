"""SSE assembly + tool-call delta reassembly (the fragmentation problem)."""
from proxy.streaming import (
    StreamAssembler,
    detect_trigger_tokens,
    message_from_completion,
    parse_sse_line,
)


def test_parse_sse_line():
    assert parse_sse_line("data: [DONE]") == "[DONE]"
    assert parse_sse_line('data: {"a": 1}') == {"a": 1}
    assert parse_sse_line("") is None
    assert parse_sse_line(": comment") is None


def test_content_reassembly():
    a = StreamAssembler()
    for piece in ["Hel", "lo ", "world"]:
        a.feed_chunk({"choices": [{"delta": {"content": piece}, "finish_reason": None}]})
    assert a.content == "Hello world"


def test_tool_call_delta_reassembly():
    a = StreamAssembler()
    # id+name arrive first, then arguments stream in fragments keyed by index
    a.feed_chunk({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "type": "function",
         "function": {"name": "search", "arguments": ""}}]}}]})
    for frag in ['{"q":', ' "rag', 's"}']:
        a.feed_chunk({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": frag}}]}}]})
    tcs = a.tool_calls()
    assert len(tcs) == 1
    assert tcs[0]["id"] == "call_1"
    assert tcs[0]["function"]["name"] == "search"
    assert tcs[0]["function"]["arguments"] == '{"q": "rags"}'


def test_two_parallel_tool_calls():
    a = StreamAssembler()
    a.feed_chunk({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c0", "function": {"name": "a", "arguments": "{}"}},
        {"index": 1, "id": "c1", "function": {"name": "b", "arguments": "{"}}]}}]})
    a.feed_chunk({"choices": [{"delta": {"tool_calls": [
        {"index": 1, "function": {"arguments": "}"}}]}}]})
    tcs = a.tool_calls()
    assert [t["id"] for t in tcs] == ["c0", "c1"]
    assert tcs[1]["function"]["arguments"] == "{}"


def test_feed_bytes_and_done():
    a = StreamAssembler()
    a.feed_bytes(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n')
    a.feed_bytes(b"data: [DONE]\n\n")
    assert a.content == "hi" and a.done


def test_feed_bytes_buffers_split_sse_line():
    a = StreamAssembler()
    a.feed_bytes(b'data: {"choices":[{"delta":{"content":"he')
    assert a.content == ""
    a.feed_bytes(b'llo"}}]}\n\n')
    a.feed_bytes(b"data: [DO")
    a.feed_bytes(b"NE]\n\n")
    assert a.content == "hello" and a.done


def test_feed_bytes_buffers_split_utf8_sequence():
    a = StreamAssembler()
    raw = 'data: {"choices":[{"delta":{"content":"cafe \u00e9"}}]}\n\n'.encode()
    split_at = raw.index("é".encode()[0])
    a.feed_bytes(raw[:split_at])
    a.feed_bytes(raw[split_at:split_at + 1])
    a.feed_bytes(raw[split_at + 1:])
    assert a.content == "cafe é"


def test_message_from_completion():
    resp = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
    assert message_from_completion(resp)["content"] == "hi"


def test_detect_trigger_tokens():
    triggers = [{"on": "token:<tool_call>", "apply": {"ref": "precision"}}]
    assert detect_trigger_tokens("now <tool_call> here", triggers) == ["precision"]
    assert detect_trigger_tokens("nothing", triggers) == []
