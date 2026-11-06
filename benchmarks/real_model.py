"""The real-model experiment: does contract-driven re-anchoring keep a real model on its rules?

A real model (see proxy/hf_upstream.py) holds a multi-turn support conversation under three
rules a deterministic checker can verify on its actual output (at most 40 words; plain text;
ends with [END]). Three arms share the model, the user turns and the re-anchor text:

  none      observe only: the reconciler records the trace, nothing is ever restated
  naive     restate the rules on a fixed cadence, whatever the state (cadence matched to the
            contract arm's number of re-anchors, as in benchmarks/t1_bench.py)
  contract  the real proxy: senses each reply, re-anchors when drift crosses the threshold
            (and on the contract's own cadence), feeds the re-anchor to the next request

Nothing here is simulated except that the user turns are scripted. Results depend on the model,
the prompts and the rules; see benchmarks/REPORT.md for how to read them.
"""
from __future__ import annotations

import dataclasses
import os
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from guidancegrid.compiler import compile_contract  # noqa: E402
from guidancegrid.controller import Reconciler  # noqa: E402
from guidancegrid.core.trace import Trace  # noqa: E402
from guidancegrid.obc import load_contract  # noqa: E402
from guidancegrid.sensors import MeasureRegistry, StructuralMeasure  # noqa: E402
from guidancegrid.store import RunRecord  # noqa: E402

CONTRACT_PATH = os.path.join(os.path.dirname(__file__), "real_model_contract.toml")
MODEL_ID = "local:qwen2.5-1.5b-instruct"          # unknown provider => T2/T3 only, which is what this is
RULES = ("brevity", "plain_text", "sign_off")
MAX_WORDS = 40
SIGN_OFF = "[END]"

SYSTEM_PROMPT = (
    "You are a support assistant for Acme Notes, a note-taking app. Follow these rules in every "
    "reply: reply in at most 40 words; use plain text only, with no markdown, lists or headings; "
    "end every reply with [END]."
)

# Some prompts invite a short plain answer; others invite exactly what the rules forbid
# (lists, tables, long explanations, code), which is where real models slip.
_PLAIN = [
    "How do I reset my password?", "Where can I find my saved notes?", "Can I use Acme Notes offline?",
    "How do I rename a notebook?", "What happens when I delete a note?", "Is my data encrypted?",
    "How do I change my email address?", "Can I share a note with a friend?", "How do I turn on dark mode?",
    "Does the app work on Android?", "How do I restore a deleted note?", "What is the maximum note size?",
    "Can I lock a note with a PIN?", "How do I contact support?", "Why is sync slow on my phone?",
    "How do I sign out on all devices?", "Can I set a reminder on a note?", "How do I merge two notebooks?",
    "Is there a free plan?", "How do I cancel my subscription?", "Can I print a note?",
    "How do I search inside a note?", "What file types can I attach?", "How do I pin a note to the top?",
]
_TEMPTING = [
    "Give me a detailed step-by-step guide, as a bulleted list, to set up two-factor authentication.",
    "Write a markdown table comparing the free and pro plans.",
    "Explain in depth, with headings, how note syncing works under the hood.",
    "List every keyboard shortcut the app supports.",
    "Show me a code snippet that calls your export API.",
    "Walk me through migrating from another notes app, numbering each step.",
    "Describe all the features in the pro plan in full detail.",
    "I want a thorough troubleshooting checklist for when notes will not sync.",
    "Write me a long, friendly welcome email for my new team members about using Acme Notes.",
    "Compare Acme Notes with its competitors point by point.",
    "Explain how to set up shared workspaces, with examples and sub-steps.",
    "Give me a full onboarding plan for a team of ten, week by week.",
    "Summarise your privacy policy in detail with bold section titles.",
    "Can you outline a backup strategy for my notes, using bullet points?",
    "Please write a detailed FAQ with at least eight questions and answers.",
    "Break down the differences between notebooks, stacks and tags with a list.",
]
POOL = _PLAIN + _TEMPTING


def kind_of(user: str) -> str:
    """'tempting' prompts ask for exactly what the rules forbid; 'plain' ones do not."""
    return "tempting" if user in _TEMPTING else "plain"


# ── the sensors: deterministic checks on the model's actual output ────
_MARKDOWN = re.compile(
    r"\*\*|__|`|^\s*#{1,6}\s|^\s*[-*•+]\s+\S|^\s*\d+[.)]\s+\S", re.MULTILINE)


def check(text: str) -> dict[str, bool]:
    """Which rules the reply follows. The sign-off is not counted towards the word limit."""
    body = text.rstrip()
    counted = body[: -len(SIGN_OFF)] if body.endswith(SIGN_OFF) else body
    return {
        "brevity": len(counted.split()) <= MAX_WORDS,
        "plain_text": _MARKDOWN.search(text) is None,
        "sign_off": body.endswith(SIGN_OFF),
    }


def make_measures() -> MeasureRegistry:
    reg = MeasureRegistry()
    for rule in RULES:
        reg.register(StructuralMeasure(
            f"structural:{rule}", lambda ctx, rule=rule: check(str(ctx.get("output", "")))[rule]))
    return reg


def contract_dict() -> dict[str, Any]:
    return load_contract(CONTRACT_PATH)


def compiled_contract():
    return compile_contract(contract_dict(), MODEL_ID)


def user_turns(seed: int, n: int = 30, plain_only: bool = False,
               shocks: tuple[int, ...] | None = None) -> list[str]:
    """A deterministic conversation, no repeats within it.

    Default: a random mix of plain and tempting prompts. ``plain_only`` drops the tempting ones (a
    violation is then drift, not the user asking for a list). ``shocks`` makes the turns at those
    indices tempting and every other turn plain: a mostly ordinary conversation with a few moments
    where the user asks for exactly what the rules forbid."""
    rng = random.Random(seed)
    if shocks is None:
        return rng.sample(_PLAIN if plain_only else POOL, n)
    if any(not 0 <= s < n for s in shocks):
        raise ValueError(f"every shock turn must be in 0..{n - 1}, got {shocks}")
    plain = rng.sample(_PLAIN, n - len(shocks))
    tempting = rng.sample(_TEMPTING, len(shocks))
    it_plain, it_tempt = iter(plain), iter(tempting)
    return [next(it_tempt) if i in shocks else next(it_plain) for i in range(n)]


def matched_every(turns: int, n_reanchors: int) -> int:
    """Fixed cadence that restates as often as the contract arm did (adherence at equal cost)."""
    return turns if n_reanchors <= 0 else max(1, round(turns / n_reanchors))


# ── results ───────────────────────────────────────────────────────────
@dataclass
class ArmResult:
    arm: str
    seed: int
    run_id: str
    trace: Trace
    tier: str
    turns: list[dict[str, Any]] = field(default_factory=list)

    @property
    def reanchor_turns(self) -> list[int]:
        return [t["turn"] for t in self.turns if t["reanchored"]]

    @property
    def corrections(self) -> list[int]:
        return [t["turn"] for t in self.turns if t["recovery"] is not None]

    @property
    def peak_drift(self) -> float:
        return max((t["drift"] for t in self.turns), default=0.0)

    def compliance(self) -> float:
        return sum(t["ok"] for t in self.turns) / len(self.turns) if self.turns else 0.0


def _turn(turn: int, user: str, reply: str, state: dict[str, Any]) -> dict[str, Any]:
    checks = check(reply)
    return {"turn": turn, "user": user, "kind": kind_of(user), "reply": reply, "checks": checks,
            "ok": all(checks.values()),
            "drift": state["drift"], "recovery": state["recovery_fired"], "reanchored": state["reanchored"]}


def _reply(resp: dict[str, Any]) -> str:
    return (resp["choices"][0]["message"].get("content") or "").strip()


def _run_record(run_id: str, trace: Trace, tier: str, contract_hash: str, cas_key: str) -> RunRecord:
    states = [r for r in trace.records if r.get("ev") == "STATE"]
    return RunRecord(
        run_id=run_id, contract_hash=contract_hash, model=MODEL_ID, tier=tier, turns=len(states),
        max_drift=round(max((s["drift"] for s in states), default=0.0), 6),
        recoveries=sum(1 for s in states if s.get("recovery_fired") in ("re_anchor", "escalate")),
        halted=any(s.get("recovery_fired") == "halt" for s in states),
        verified=trace.verify(), trace_hash=trace.head, trace_cas_key=cas_key, created="2026-11-06",
    )


# ── arms ──────────────────────────────────────────────────────────────
PLACEMENTS = ("front", "end")


def _with_restatement(messages: list[dict[str, str]], text: str, placement: str) -> list[dict[str, str]]:
    """Add a re-anchor to a request. 'front' is where the proxy puts it (first message); 'end' puts it
    immediately before the latest user message."""
    note = {"role": "system", "content": text}
    return [note, *messages] if placement == "front" else [*messages[:-1], note, messages[-1]]


async def _run_observed(arm: str, upstream, seed: int, turns: int, every: int, store,
                        placement: str = "front", plain_only: bool = False,
                        shocks: tuple[int, ...] | None = None) -> ArmResult:
    """The none and naive arms. The reconciler only *records*: its recovery ladder is switched off
    so the trace never claims a correction nobody applied, and its cadence is the arm's own
    (0 = never restate). A re-anchor prepared at turn t is sent with the request at turn t+1,
    exactly as the proxy does."""
    if placement not in PLACEMENTS:
        raise ValueError(f"placement must be one of {PLACEMENTS}, got {placement!r}")
    base = compiled_contract()
    cc = dataclasses.replace(
        base,
        recovery=dataclasses.replace(base.recovery, ladder=[]),
        reanchor_plan={"every": every, "on_recovery": False, "budget_chars": 600},
    )
    manifest = {"model": MODEL_ID, "contract_hash": cc.contract_hash, "runtime": "openguide-real-model-0.1",
                "arm": arm, "seed": seed, "simulated": False}
    rc = Reconciler(cc, make_measures(), manifest)
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    pending: str | None = None
    out: list[dict[str, Any]] = []
    for t, user in enumerate(user_turns(seed, turns, plain_only, shocks)):
        messages = history + [{"role": "user", "content": user}]
        sent = _with_restatement(messages, pending, placement) if pending else messages
        reply = _reply(await upstream.chat({"model": MODEL_ID, "messages": sent}, {}))
        step = rc.step(t, {"turn": t, "output": reply, "messages": messages})
        pending = step.reanchor_text
        out.append(_turn(t, user, reply, step.state))
        history = messages + [{"role": "assistant", "content": reply}]
    run_id = f"real-{arm}-s{seed}"
    if store is not None:
        key = store.put_trace(rc.trace)
        store.put_run(_run_record(run_id, rc.trace, cc.tier_active, cc.contract_hash, key))
    return ArmResult(arm, seed, run_id, rc.trace, cc.tier_active, out)


async def run_none(upstream, seed: int, turns: int = 30, store=None, arm: str = "none",
                   plain_only: bool = False, shocks: tuple[int, ...] | None = None) -> ArmResult:
    """Observe only. ``arm`` labels the run (e.g. a T0-steered variant) so variants never collide."""
    return await _run_observed(arm, upstream, seed, turns, every=0, store=store, plain_only=plain_only,
                               shocks=shocks)


async def run_naive(upstream, seed: int, turns: int = 30, every: int = 8, store=None,
                    placement: str = "front", arm: str = "naive", plain_only: bool = False,
                    shocks: tuple[int, ...] | None = None) -> ArmResult:
    return await _run_observed(arm, upstream, seed, turns, every=every, store=store, placement=placement,
                               plain_only=plain_only, shocks=shocks)


async def run_contract(upstream, seed: int, turns: int = 30, store=None, plain_only: bool = False,
                       shocks: tuple[int, ...] | None = None) -> ArmResult:
    """The real proxy: governed requests through create_app, one session per conversation."""
    import httpx

    from proxy.app import create_app
    from proxy.registry import ContractRegistry

    registry = ContractRegistry(measures=make_measures())
    h = registry.register(contract_dict())
    app = create_app(registry=registry, upstream=upstream, store=store)
    sid = f"real-contract-s{seed}"
    headers = {"X-OpenGuide-Contract": h, "X-OpenGuide-Session": sid}
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    replies: list[tuple[int, str, str]] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy", timeout=600) as client:
        for t, user in enumerate(user_turns(seed, turns, plain_only, shocks)):
            messages = history + [{"role": "user", "content": user}]
            r = await client.post("/v1/chat/completions", headers=headers,
                                  json={"model": MODEL_ID, "messages": messages})
            r.raise_for_status()
            reply = _reply(r.json())
            replies.append((t, user, reply))
            history = messages + [{"role": "assistant", "content": reply}]
    sess = app.state.governor.sessions.get(sid)
    states = [s for s in sess.reconciler.trace.records if s.get("ev") == "STATE"]
    out = [_turn(t, u, rep, states[t]) for t, u, rep in replies]
    return ArmResult("contract", seed, sid, sess.reconciler.trace, sess.compiled.tier_active, out)


def _rate(turns: list[dict[str, Any]]) -> float | None:
    return (sum(t["ok"] for t in turns) / len(turns)) if turns else None


def _after_first_tempting(results: list["ArmResult"]) -> list[dict[str, Any]]:
    """Plain turns that come after the first tempting turn of their conversation: the turns where a
    contract could be restoring behaviour, as opposed to the user explicitly asking for a violation."""
    out: list[dict[str, Any]] = []
    for r in results:
        first = next((t["turn"] for t in r.turns if t["kind"] == "tempting"), None)
        if first is not None:
            out += [t for t in r.turns if t["turn"] > first and t["kind"] == "plain"]
    return out


# ── summary ───────────────────────────────────────────────────────────
def summarize(by_arm: dict[str, list[ArmResult]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for arm, results in by_arm.items():
        turns = [t for r in results for t in r.turns]
        n = len(turns)
        k = len(results)
        out[arm] = {
            "conversations": k,
            "turns": n,
            "compliance": (sum(t["ok"] for t in turns) / n) if n else None,
            "by_rule": {r: ((sum(t["checks"][r] for t in turns) / n) if n else None) for r in RULES},
            "by_kind": {k: _rate([t for t in turns if t["kind"] == k]) for k in ("plain", "tempting")},
            "recovery": _rate(_after_first_tempting(results)),
            "reanchors_per_conversation": (sum(len(r.reanchor_turns) for r in results) / k) if k else None,
            "mean_peak_drift": (sum(r.peak_drift for r in results) / k) if k else None,
        }
    return out
