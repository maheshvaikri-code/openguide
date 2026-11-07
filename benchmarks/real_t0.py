"""Real T0 (activation steering) gate on an open-weight model.

Questions, measured on the real model rather than simulated:
  1. Can a steering vector derived from the model's own activations make it follow the rules
     WITHOUT being told them? (instruction replacement)
  2. Does steering stop the drift seen in a long conversation, even when it IS told the rules?
  3. What does steering cost in capability? (GSM8K accuracy and MMLU accuracy with vs without)

The steering direction is the mean difference of the residual stream at the last prompt token
between "system prompt states the rules" and "system prompt does not", per layer in a band. It is
scaled to the typical residual norm at that layer, so gain 1.0 means one typical norm. Injection
uses the norm-preserving ActivationSteerer in guidancegrid/channels/t0_activation.py.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import numpy as np

from benchmarks import real_model as rm
from benchmarks.replication import wilson  # noqa: F401  (re-exported: the one definition lives there)
from guidancegrid.channels.t0_activation import SIGNAL, decoder_layers, steering_context
from guidancegrid.core.grid import SignalPack

__all__ = [
    "SIGNAL", "decoder_layers", "last_token_states", "build_pack", "steering_context", "extract_number",
    "gsm8k_gold", "same_number", "mmlu_prompt", "compliance", "wilson", "generate_batch", "mmlu_scores",
]


# ── deriving the steering vectors ─────────────────────────────────────
def last_token_states(model, input_ids, attention_mask, layers: list[int]) -> dict[int, np.ndarray]:
    """Residual stream after each given decoder layer, at the last token: {layer: (N, d) float32}.
    Inputs must be left-padded so the last position is the last real token. Do not ask for the final
    layer: HF returns that one after the final norm."""
    import torch

    with torch.no_grad():
        out = model(input_ids=input_ids, attention_mask=attention_mask, output_hidden_states=True)
    return {layer: out.hidden_states[layer + 1][:, -1, :].float().cpu().numpy() for layer in layers}


def build_pack(model_id: str, with_rules: dict[int, np.ndarray],
               without: dict[int, np.ndarray]) -> SignalPack:
    """Per layer: unit(mean(with) - mean(without)) scaled to the typical residual norm there."""
    if set(with_rules) != set(without):
        raise ValueError("both conditions must cover the same layers")
    d = int(next(iter(with_rules.values())).shape[1])
    pack = SignalPack(model_id, d)
    for layer in sorted(with_rules):
        diff = with_rules[layer].mean(axis=0) - without[layer].mean(axis=0)
        norm = float(np.linalg.norm(diff))
        if norm < 1e-9:
            continue                                         # the conditions don't differ here: no direction
        typical = float(np.linalg.norm(np.concatenate([with_rules[layer], without[layer]]), axis=1).mean())
        pack.set_vector(SIGNAL, layer, (diff / norm * typical).astype(np.float32))
    return pack


# ── generation and scoring on a real tokenizer/model ──────────────────
def generate_batch(model, tok, system: str, users: list[str], max_new: int,
                   ctx: Callable[[], Any]) -> list[str]:
    """Greedy chat replies for a batch of single-turn prompts (left-padded), under ``ctx``."""
    import torch

    texts = [tok.apply_chat_template([{"role": "system", "content": system}, {"role": "user", "content": u}],
                                     add_generation_prompt=True, tokenize=False) for u in users]
    enc = tok(texts, return_tensors="pt", padding=True).to(model.device)
    with torch.no_grad(), ctx():
        out = model.generate(**enc, max_new_tokens=max_new, do_sample=False, pad_token_id=tok.eos_token_id)
    n = int(enc["input_ids"].shape[1])
    return [tok.decode(o[n:], skip_special_tokens=True).strip() for o in out]


def mmlu_scores(model, tok, prompts: list[str], ctx: Callable[[], Any]) -> list[int]:
    """Index (0-3) of the option letter the model finds most likely next, for each prompt."""
    import torch

    ids = [tok.encode(letter, add_special_tokens=False)[0] for letter in "ABCD"]
    texts = [
        tok.apply_chat_template([{"role": "user", "content": p}], add_generation_prompt=True, tokenize=False)
        for p in prompts
    ]
    enc = tok(texts, return_tensors="pt", padding=True).to(model.device)
    with torch.no_grad(), ctx():
        logits = model(**enc).logits[:, -1, :]
    return [int(torch.argmax(row[ids])) for row in logits]


# ── evaluators (pure) ─────────────────────────────────────────────────
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _norm(s: str) -> str | None:
    try:
        d = Decimal(s.replace(",", "")).normalize()
    except InvalidOperation:
        return None
    return format(d, "f")


def extract_number(text: str) -> str | None:
    """The last number in a reply, normalised (commas and trailing zeros removed)."""
    found = _NUM.findall(text or "")
    return _norm(found[-1]) if found else None


def gsm8k_gold(answer: str) -> str | None:
    return _norm(answer.split("####")[-1].strip())


def same_number(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return Decimal(a.replace(",", "")) == Decimal(b.replace(",", ""))
    except InvalidOperation:
        return False


def mmlu_prompt(question: str, choices: list[str]) -> str:
    opts = "\n".join(f"{letter}. {c}" for letter, c in zip("ABCD", choices))
    return f"{question}\n{opts}\nAnswer with only the letter"


def compliance(replies: list[str]) -> dict[str, Any]:
    """Share of replies that follow all rules, and each rule, by the same checker the experiment uses."""
    n = len(replies)
    checks = [rm.check(r) for r in replies]
    return {
        "n": n,
        "all": (sum(all(c.values()) for c in checks) / n) if n else None,
        **{rule: ((sum(c[rule] for c in checks) / n) if n else None) for rule in rm.RULES},
    }

