"""Rebuild saved real-model runs with message text, by replaying the model's recorded replies.

The experiment scripts save every turn (what was asked, what the model replied, every check). The
rules engine is deterministic: given the same replies it produces the same STATE records. So the runs
can be reconstructed, now with the text of each turn inside the hash chain, without touching the GPU.

Fidelity is the point. Each replayed turn must reproduce the recorded drift, action, re-anchor and rule
results exactly, and the replayed prompts must match. If anything differs, nothing is written: a rebuild
may add detail to the data, never substitute different data.
"""
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from benchmarks import real_model as rm
from guidancegrid.store import Store

# saved arm name -> (kind, placement, restate every N turns)
SPECS: dict[str, tuple[str, str | None, int]] = {
    "none": ("none", None, 0),
    "proxy": ("proxy", None, 0),
    "front1": ("naive", "front", 1), "front3": ("naive", "front", 3),
    "end1": ("naive", "end", 1), "end3": ("naive", "end", 3),
}
_FIELDS = ("user", "drift", "recovery", "reanchored", "ok", "checks")


class FidelityError(Exception):
    """The replay did not reproduce the recording (or asked for more than was recorded)."""


class ReplayUpstream:
    """An Upstream that answers with the recorded replies, in order."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self._i = 0

    async def chat(self, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        if self._i >= len(self._replies):
            raise FidelityError("the replay asked for more replies than were recorded")
        reply = self._replies[self._i]
        self._i += 1
        return {"id": f"replay-{self._i}", "object": "chat.completion", "model": body.get("model", "replay"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

    def stream(self, body, headers):  # pragma: no cover - the experiments never stream
        raise NotImplementedError("ReplayUpstream does not stream")


async def _replay(name: str, conv: dict[str, Any], turns: int, shocks, plain_only: bool, tag: str,
                  store: Store) -> rm.ArmResult:
    kind, placement, every = SPECS[name]
    up = ReplayUpstream([t["reply"] for t in conv["turns"]])
    seed, arm = conv["seed"], f"{tag}-{name}"
    kw = {"plain_only": plain_only, "shocks": shocks}
    if kind == "none":
        return await rm.run_none(up, seed, turns, store, arm=arm, **kw)
    if kind == "proxy":
        return await rm.run_contract(up, seed, turns, store, **kw)
    return await rm.run_naive(up, seed, turns, every, store, placement=placement or "front", arm=arm, **kw)


def _verify(name: str, seed: int, recorded: list[dict[str, Any]], replayed: list[dict[str, Any]]) -> None:
    if len(recorded) != len(replayed):
        raise FidelityError(f"{name} seed {seed}: {len(recorded)} turns recorded, {len(replayed)} replayed")
    for rec, new in zip(recorded, replayed):
        for field in _FIELDS:
            if rec.get(field) != new.get(field):
                raise FidelityError(f"{name} seed {seed} turn {rec.get('turn')}: {field} differs "
                                    f"(recorded {rec.get(field)!r}, replayed {new.get(field)!r})")


def rebuild(saved: dict[str, Any], store: Store, tag: str) -> int:
    """Replay every saved conversation into ``store`` (replacing runs with the same ids). Returns how many
    runs were written. All conversations are replayed and checked in a scratch store first, so a mismatch
    anywhere leaves ``store`` untouched."""
    arms = saved["conversations"]
    unknown = [a for a in arms if a not in SPECS]
    if unknown:
        raise FidelityError(f"don't know how to replay arm(s): {', '.join(unknown)}")
    turns = int(saved["turns"])
    shocks = tuple(saved["shocks"]) if saved.get("shocks") else None
    plain_only = bool(saved.get("plain_only", False))

    scratch = Store()
    replayed: list[rm.ArmResult] = []
    for name, convs in arms.items():
        for conv in convs:
            res = asyncio.run(_replay(name, conv, turns, shocks, plain_only, tag, scratch))
            _verify(name, conv["seed"], conv["turns"], res.turns)
            replayed.append(res)

    for res in replayed:                                  # verified: now copy into the real store
        row = scratch.get_run(res.run_id)
        trace = scratch.get_trace(row.trace_cas_key)
        store.put_run(dataclasses.replace(row, trace_cas_key=store.put_trace(trace)))
    return len(replayed)
