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

import numpy as np

from .steering import MAX_SAFE_GAIN, MAX_VECTOR_NORM_RATIO, SteerReceipt
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
        # gain -> context manager that steers the activations while it is open (ADR-003). Set by
        # enable_steering; the Governor passes a gain per call, a client never can.
        self.steer_factory: Callable[[float], AbstractContextManager[Any]] | None = None
        # forward passes the steering field covers (set by enable_steering)
        self._steer_steps: int | None = None

    @property
    def supports_steering(self) -> bool:
        return self.steer_factory is not None

    def _typical_residual_norms(self, n_layers: int) -> dict[int, float]:
        """Median per-token residual norm after each decoder layer on a fixed token sequence (the last layer
        is returned after the final norm by HF, so it is left out)."""
        import torch

        vocab = int(getattr(self.model.config, "vocab_size", 1000))
        ids = torch.arange(1, 33).clamp(max=vocab - 1).unsqueeze(0).to(self.model.device)
        with torch.no_grad():
            states = self.model(input_ids=ids, output_hidden_states=True).hidden_states
        return {i: float(states[i + 1][0].float().norm(dim=-1).median()) for i in range(n_layers - 1)}

    def enable_steering(self, config: Any) -> "HFUpstream":
        """Let the Governor steer this model's activations (T0). Checks the pack against the model now, so a
        mismatch fails at start-up rather than on the first corrected turn. Imports torch only here."""
        if self.model is None:
            raise ValueError("steering needs the model itself: build this upstream with from_pretrained")
        from guidancegrid.channels.t0_activation import MAX_STEPS, decoder_layers, steering_context
        from guidancegrid.core.grid import STEER_SIGNAL

        n_layers = len(decoder_layers(self.model))
        lo, hi = config.band
        if hi > n_layers:
            raise ValueError(f"the steering band {config.band} reaches past the model's {n_layers} layers")
        hidden = getattr(getattr(self.model, "config", None), "hidden_size", None)
        if hidden is not None and int(hidden) != int(config.pack.d):
            raise ValueError(f"the steering pack was made for hidden size {config.pack.d}, "
                             f"this model's hidden size is {hidden}")
        if self.max_new_tokens + 1 > MAX_STEPS:            # the gain field covers a fixed number of passes
            raise ValueError(f"max_new_tokens={self.max_new_tokens} is longer than steering covers "
                             f"({MAX_STEPS - 1}); lower max_new_tokens, or steering would stop mid-reply")
        # The gain only bounds the push if the vector is on the model's own scale (see MAX_VECTOR_NORM_RATIO).
        typical = self._typical_residual_norms(n_layers)
        for layer in range(lo, hi):
            if layer not in typical:
                continue                                         # the last layer is read after the final norm
            norm = float(np.linalg.norm(np.asarray(config.pack.get(STEER_SIGNAL, layer), dtype=np.float64)))
            if norm > MAX_VECTOR_NORM_RATIO * typical[layer]:
                raise ValueError(
                    f"the steering pack's norm at layer {layer} is {norm:.3g}, over "
                    f"{MAX_VECTOR_NORM_RATIO:g}x "
                    f"this model's typical residual norm {typical[layer]:.3g}: it would replace the hidden "
                    f"state instead of nudging it, whatever the gain")
        model, pack, band = self.model, config.pack_in_band(), tuple(config.band)
        self._steer_steps = MAX_STEPS
        manifest = config.manifest(self.served_name)
        self.steer_factory = lambda gain: steering_context(model, pack, band, gain, manifest)()
        return self

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
    async def chat(self, body: dict[str, Any], headers: dict[str, str], steer: float = 0.0,
                   receipt: SteerReceipt | None = None) -> dict[str, Any]:
        if steer > 0 and self.steer_factory is None:
            raise ValueError("asked to steer, but this upstream cannot steer (call enable_steering first)")
        if steer > MAX_SAFE_GAIN:
            raise ValueError(f"steering gain {steer} is above the safe ceiling {MAX_SAFE_GAIN}")
        messages = [{"role": m.get("role", "user"), "content": _flatten(m.get("content"))}
                    for m in body.get("messages", [])]
        if not messages:
            raise ValueError("messages must contain at least one message")
        want = body.get("max_tokens") or body.get("max_completion_tokens") or self.max_new_tokens
        max_new = max(1, min(int(want), self.max_new_tokens))      # never above the configured ceiling
        if steer > 0 and self._steer_steps is not None and max_new + 1 > self._steer_steps:
            raise ValueError(f"a steered reply of up to {max_new} tokens is longer than steering covers "
                             f"({self._steer_steps - 1})")

        def run() -> tuple[str, int, int]:
            with self._lock:
                self.calls += 1
                with (self.around() if self.around else nullcontext()):
                    with (self.steer_factory(steer) if steer > 0 and self.steer_factory else nullcontext()):
                        result = self._generate(messages, max_new)
                        if steer > 0 and receipt is not None:
                            receipt.produced = True    # a reply now exists, written under steering
                        return result

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

    async def stream(self, body: dict[str, Any], headers: dict[str, str], steer: float = 0.0,
                     receipt: SteerReceipt | None = None) -> AsyncIterator[bytes]:
        # The model generates the full reply first, then it is replayed as SSE chunks: the
        # wire format is a real stream, the token timing is not.
        comp = await self.chat(body, headers, steer=steer, receipt=receipt)
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
