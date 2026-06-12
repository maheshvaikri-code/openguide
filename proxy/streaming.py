"""SSE assembly + tool-call delta reassembly.

Streaming responses arrive as ``data: {chunk}`` lines whose ``delta`` carries
partial content and *fragmented* tool calls (the function ``arguments`` string
is split across many chunks, keyed by ``index``). To run sensors on a turn we
need the whole assembled message, so the assembler folds deltas back into one
message while the raw bytes still pass straight through to the client.
"""
from __future__ import annotations

import json
from typing import Any


def parse_sse_line(line: str) -> dict[str, Any] | None | str:
    """Parse one SSE line. Returns a chunk dict, the sentinel ``"[DONE]"``, or
    None for blank/non-data lines."""
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return "[DONE]"
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


class StreamAssembler:
    """Folds streamed chunks into a single assistant message."""

    def __init__(self) -> None:
        self.role = "assistant"
        self.content_parts: list[str] = []
        self._tools: dict[int, dict[str, Any]] = {}
        self.finish_reason: str | None = None
        self.done = False

    def feed_chunk(self, chunk: dict[str, Any]) -> None:
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            if "role" in delta and delta["role"]:
                self.role = delta["role"]
            if delta.get("content"):
                self.content_parts.append(delta["content"])
            for tc in delta.get("tool_calls", []) or []:
                idx = tc.get("index", 0)
                slot = self._tools.setdefault(idx, {"id": None, "type": "function",
                                                    "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                if tc.get("type"):
                    slot["type"] = tc["type"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]

    def feed_bytes(self, raw: bytes) -> None:
        """Feed a raw SSE byte chunk (may contain several lines)."""
        for line in raw.decode("utf-8", errors="replace").splitlines():
            parsed = parse_sse_line(line)
            if parsed == "[DONE]":
                self.done = True
            elif isinstance(parsed, dict):
                self.feed_chunk(parsed)

    @property
    def content(self) -> str:
        return "".join(self.content_parts)

    def tool_calls(self) -> list[dict[str, Any]]:
        return [self._tools[i] for i in sorted(self._tools)]

    def message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        tcs = self.tool_calls()
        if tcs:
            msg["tool_calls"] = tcs
        return msg


def message_from_completion(resp: dict[str, Any]) -> dict[str, Any]:
    """Extract the assistant message from a non-streaming completion."""
    choices = resp.get("choices") or [{}]
    return choices[0].get("message", {"role": "assistant", "content": ""})


def detect_trigger_tokens(text: str, triggers: list[dict[str, Any]]) -> list[str]:
    """Return the refs of ``token:<...>`` triggers whose token appears in text."""
    fired: list[str] = []
    for trig in triggers:
        on = str(trig.get("on", ""))
        if on.startswith("token:"):
            token = on[len("token:"):]
            if token and token in text:
                ref = trig.get("apply", {}).get("ref")
                if ref:
                    fired.append(ref)
    return fired
