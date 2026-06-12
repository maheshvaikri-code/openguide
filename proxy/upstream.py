"""Upstream LLM client abstraction.

The proxy forwards to any OpenAI-compatible endpoint. The Upstream protocol is
injectable so tests run fully offline against a MockUpstream — no network, no
API key — while production uses HttpxUpstream.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol


class Upstream(Protocol):
    async def chat(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        """Non-streaming completion: return the parsed JSON response."""
        ...

    def stream(self, body: dict[str, Any], headers: dict[str, str]) -> AsyncIterator[bytes]:
        """Streaming completion: yield raw SSE lines (``data: {...}\\n\\n``)."""
        ...


class HttpxUpstream:
    """Real OpenAI-compatible upstream over httpx."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, headers: dict[str, str]) -> dict[str, str]:
        out = {"content-type": "application/json"}
        if self.api_key:
            out["authorization"] = f"Bearer {self.api_key}"
        # forward an explicit per-request key if the caller supplied one
        if "authorization" in {k.lower() for k in headers}:
            for k, v in headers.items():
                if k.lower() == "authorization":
                    out["authorization"] = v
        return out

    async def chat(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.base_url}/v1/chat/completions", json=body, headers=self._headers(headers)
            )
            r.raise_for_status()
            return r.json()

    async def stream(self, body: dict[str, Any], headers: dict[str, str]) -> AsyncIterator[bytes]:
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/v1/chat/completions",
                json={**body, "stream": True}, headers=self._headers(headers),
            ) as r:
                r.raise_for_status()
                async for chunk in r.aiter_raw():
                    yield chunk


class MockUpstream:
    """Scripted upstream for tests.

    ``responder(body) -> assistant_text | dict`` lets a test control the model's
    output (e.g. to simulate instruction drift). If it returns a string, it is
    wrapped in a standard chat completion; a dict is returned verbatim.
    """

    def __init__(self, responder=None, *, model: str = "mock:agent-v1"):
        self.model = model
        self.responder = responder or (lambda body: "ok")
        self.calls: list[dict[str, Any]] = []

    def _completion(self, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(body)
        out = self.responder(body)
        if isinstance(out, dict):
            return out
        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "model": body.get("model", self.model),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": out},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def chat(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        return self._completion(body)

    async def stream(self, body: dict[str, Any], headers: dict[str, str]) -> AsyncIterator[bytes]:
        import json

        comp = self._completion(body)
        content = comp["choices"][0]["message"].get("content") or ""
        cid = comp["id"]
        model = comp["model"]
        # role chunk, then token-ish chunks, then finish, then [DONE]
        first = {"id": cid, "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
        yield f"data: {json.dumps(first)}\n\n".encode()
        for piece in _chunk_text(content):
            d = {"id": cid, "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
            yield f"data: {json.dumps(d)}\n\n".encode()
        fin = {"id": cid, "object": "chat.completion.chunk", "model": model,
               "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(fin)}\n\n".encode()
        yield b"data: [DONE]\n\n"


def _chunk_text(text: str, n: int = 8):
    for i in range(0, len(text), n):
        yield text[i:i + n]
