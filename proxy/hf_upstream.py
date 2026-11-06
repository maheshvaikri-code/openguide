"""An in-process local-model Upstream (Hugging Face transformers).

Lets the proxy govern a real model on this machine with no HTTP server and no new dependency:
torch and transformers are imported lazily, only when a real model is loaded. Generation is
greedy (deterministic), serialised with a lock (one GPU), and run in a worker thread so the
event loop is never blocked.

    up = HFUpstream.from_pretrained(".models/Qwen2.5-1.5B-Instruct")
    app = create_app(upstream=up, ...)

Tests inject ``generate_fn`` instead of loading weights.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import AbstractContextManager, nullcontext
from typing import Any, AsyncIterator, Callable

from .upstream import _chunk_text

# (messages, max_new_tokens) -> (text, prompt_tokens, completion_tokens)
GenerateFn = Callable[[list[dict[str, str]], int], tuple[str, int, int]]


def _flatten(content: Any) -> str:
    """OpenAI content may be a string or a list of parts; keep the text parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type", "text") == "text")
    return "" if content is None else str(content)


class HFUpstream:
    def __init__(self, generate_fn: GenerateFn, *, served_name: str = "local:hf-model",
                 max_new_tokens: int = 128):
        self._generate = generate_fn
        self.served_name = served_name
        self.max_new_tokens = max_new_tokens
        self._lock = threading.Lock()            # one generation at a time (one GPU)
        self.calls = 0
        # Optional factory of a context manager entered around each generation (inside the lock),
        # e.g. to register and then remove activation-steering hooks. Always exited, even on error.
        self.around: Callable[[], AbstractContextManager[Any]] | None = None
        # set by from_pretrained, so callers that need the model itself (e.g. steering) can reach it
        self.model: Any = None
        self.tokenizer: Any = None

    # ── loading a real model ─────────────────────────────────────────
    @classmethod
    def from_pretrained(cls, path: str, *, served_name: str | None = None, max_new_tokens: int = 128,
                        device: str | None = None) -> "HFUpstream":
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        tok = AutoTokenizer.from_pretrained(path)
        model = AutoModelForCausalLM.from_pretrained(
            path, dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()

        def generate(messages: list[dict[str, str]], max_new: int) -> tuple[str, int, int]:
            ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt",
                                          return_dict=True).to(dev)
            with torch.no_grad():
                out = model.generate(**ids, max_new_tokens=max_new, do_sample=False,
                                     pad_token_id=tok.eos_token_id)
            n_prompt = int(ids["input_ids"].shape[1])
            new = out[0, n_prompt:]
            return tok.decode(new, skip_special_tokens=True).strip(), n_prompt, int(new.shape[0])

        name = served_name or "local:" + path.replace("\\", "/").rstrip("/").split("/")[-1].lower()
        inst = cls(generate, served_name=name, max_new_tokens=max_new_tokens)
        inst.model, inst.tokenizer = model, tok
        return inst

    # ── Upstream protocol ────────────────────────────────────────────
    async def chat(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        messages = [{"role": m.get("role", "user"), "content": _flatten(m.get("content"))}
                    for m in body.get("messages", [])]
        if not messages:
            raise ValueError("messages must contain at least one message")
        want = body.get("max_tokens") or body.get("max_completion_tokens") or self.max_new_tokens
        max_new = max(1, min(int(want), self.max_new_tokens))      # never above the configured ceiling

        def run() -> tuple[str, int, int]:
            with self._lock:
                self.calls += 1
                with (self.around() if self.around else nullcontext()):
                    return self._generate(messages, max_new)

        text, n_in, n_out = await asyncio.to_thread(run)
        return {
            "id": f"chatcmpl-local-{self.calls}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", self.served_name),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out},
        }

    async def stream(self, body: dict[str, Any], headers: dict[str, str]) -> AsyncIterator[bytes]:
        # The model generates the full reply first, then it is replayed as SSE chunks: the
        # wire format is a real stream, the token timing is not.
        comp = await self.chat(body, headers)
        text = comp["choices"][0]["message"]["content"]
        cid, model = comp["id"], comp["model"]

        def chunk(delta: dict[str, Any], finish: str | None = None) -> bytes:
            d = {"id": cid, "object": "chat.completion.chunk", "model": model,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(d)}\n\n".encode()

        yield chunk({"role": "assistant"})
        for piece in _chunk_text(text):
            yield chunk({"content": piece})
        yield chunk({}, "stop")
        yield b"data: [DONE]\n\n"
