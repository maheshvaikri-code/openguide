"""Real T0 gate: activation steering on a real open-weight model, measured end to end.

    python scripts/real_t0_gate.py                      # all three evaluations
    python scripts/real_t0_gate.py --skip-drift         # evaluations 1 and 3 only (fast)

  1. Instruction replacement: does steering make the model follow the rules with NO rules in its prompt?
  2. Recovery: after the user asks for what the rules forbid, does steering keep/restore compliance?
     Same conversations as scripts/real_placement_ablation.py (16 turns, shocks at 4 and 10), so the
     steered arms compare directly with the none / proxy / re-anchor arms.
  3. Capability: GSM8K and MMLU accuracy with vs without steering.

The vectors are derived on prompts that are not in any evaluation set. Needs .models/Qwen2.5-1.5B-Instruct
and a GPU. Writes benchmarks/real_t0_results.json. ASCII-only output (Windows consoles).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from benchmarks import real_model as rm  # noqa: E402
from benchmarks import real_t0 as t0  # noqa: E402
from guidancegrid.store import Store  # noqa: E402
from proxy.hf_upstream import HFUpstream  # noqa: E402

MODEL = os.path.join(ROOT, ".models", "Qwen2.5-1.5B-Instruct")
DB = os.path.join(ROOT, ".console-demo", "real-model.db")
OUT = os.path.join(ROOT, "benchmarks", "real_t0_results.json")
MMLU_DIR = os.path.join(ROOT, ".models", "mmlu")
BASE_SYSTEM = "You are a support assistant for Acme Notes, a note-taking app."
GAINS = (0.1, 0.2, 0.4, 0.6, 0.8)
BAND = (10, 19)                                   # decoder layers 10..18 of 28, fixed in advance
# Held-out derivation prompts: not in benchmarks/real_model.py's pool, and not used to evaluate.
DERIVATION_PROMPTS = [
    "How do I export a note as a PDF?", "Can I add a photo to a note?", "How do I create a new notebook?",
    "Where do I find the trash folder?", "How do I enable notifications?", "Can I change the font size?",
    "How do I invite a teammate?", "What is the storage limit?", "How do I recover my account?",
    "Can I sort notes by date?", "How do I duplicate a note?", "Can I change my username?",
]
GSM8K_INSTRUCTION = "\nSolve this step by step, then finish with: The answer is <number>."


def say(msg: str) -> None:
    print(msg, flush=True)


def chat_ids(tok, system: str, users: list[str], device):
    texts = [tok.apply_chat_template([{"role": "system", "content": system}, {"role": "user", "content": u}],
                                     add_generation_prompt=True, tokenize=False) for u in users]
    enc = tok(texts, return_tensors="pt", padding=True).to(device)
    return enc["input_ids"], enc["attention_mask"]


def derive(up) -> t0.SignalPack:
    layers = list(range(*BAND))
    with_rules = t0.last_token_states(up.model, *chat_ids(up.tokenizer, rm.SYSTEM_PROMPT, DERIVATION_PROMPTS,
                                                          up.model.device), layers)
    without = t0.last_token_states(up.model, *chat_ids(up.tokenizer, BASE_SYSTEM, DERIVATION_PROMPTS,
                                                       up.model.device), layers)
    return t0.build_pack("qwen2.5-1.5b-instruct", with_rules, without)


def ctx_for(up, pack, gain):
    return t0.steering_context(up.model, pack, BAND, gain, {"model": rm.MODEL_ID, "pack_hash": pack.hash()})


def batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def eval_instruction_replacement(up, pack) -> dict:
    users = rm._PLAIN
    rows = {}
    for label, system in (("no rules in prompt", BASE_SYSTEM), ("rules in prompt", rm.SYSTEM_PROMPT)):
        for g in (0.0, *GAINS):
            replies = []
            for b in batches(users, 12):
                replies += t0.generate_batch(up.model, up.tokenizer, system, b, 96, ctx_for(up, pack, g))
            c = t0.compliance(replies)
            rows[f"{label} | gain {g}"] = {**c, "sample": replies[:2]}
            say(f"  {label:20s} gain {g:<4g}: all rules {c['all']:5.0%}  brevity {c['brevity']:4.0%} "
                f"plain {c['plain_text']:4.0%} sign-off {c['sign_off']:4.0%}")
    return rows


def load_gsm8k(n: int):
    from datasets import load_dataset

    ds = load_dataset("openai/gsm8k", "main", split="test")
    idx = random.Random(0).sample(range(len(ds)), n)
    return [(ds[i]["question"], t0.gsm8k_gold(ds[i]["answer"])) for i in idx]


def load_mmlu(n: int):
    import pandas as pd
    from huggingface_hub import hf_hub_download

    path = hf_hub_download("cais/mmlu", "all/test-00000-of-00001.parquet", repo_type="dataset",
                           local_dir=MMLU_DIR)
    df = pd.read_parquet(path)
    idx = random.Random(0).sample(range(len(df)), n)
    return [(t0.mmlu_prompt(df.iloc[i]["question"], list(df.iloc[i]["choices"])), int(df.iloc[i]["answer"]))
            for i in idx]


def eval_capability(up, pack, gsm_n: int, mmlu_n: int) -> dict:
    out: dict = {"gsm8k": {}, "mmlu": {}}
    try:
        gsm = load_gsm8k(gsm_n)
    except Exception as e:                                   # noqa: BLE001 - report, never fake
        gsm = None
        out["gsm8k"] = {"not_measured": f"{type(e).__name__}: {e}"}
    try:
        mmlu = load_mmlu(mmlu_n)
    except Exception as e:                                   # noqa: BLE001
        mmlu = None
        out["mmlu"] = {"not_measured": f"{type(e).__name__}: {e}"}
    for g in (0.0, *GAINS):
        ctx = ctx_for(up, pack, g)
        if gsm:
            ok = 0
            for b in batches(gsm, 20):
                replies = t0.generate_batch(up.model, up.tokenizer, BASE_SYSTEM,
                                            [q + GSM8K_INSTRUCTION for q, _ in b], 320, ctx)
                ok += sum(t0.same_number(t0.extract_number(r), gold) for r, (_, gold) in zip(replies, b))
            lo, hi = t0.wilson(ok, len(gsm))
            out["gsm8k"][str(g)] = {"correct": ok, "n": len(gsm), "acc": ok / len(gsm), "ci95": [lo, hi]}
        if mmlu:
            ok = 0
            for b in batches(mmlu, 25):
                picks = t0.mmlu_scores(up.model, up.tokenizer, [p for p, _ in b], ctx)
                ok += sum(p == gold for p, (_, gold) in zip(picks, b))
            lo, hi = t0.wilson(ok, len(mmlu))
            out["mmlu"][str(g)] = {"correct": ok, "n": len(mmlu), "acc": ok / len(mmlu), "ci95": [lo, hi]}
        say(f"  gain {g:<4g}: GSM8K {out['gsm8k'].get(str(g), {}).get('acc', float('nan')):5.1%}   "
            f"MMLU {out['mmlu'].get(str(g), {}).get('acc', float('nan')):5.1%}")
    return out


def replay_check(up, pack) -> dict:
    """Same prompt, same gain, twice: the steering trace head must be bit-identical."""
    heads = []
    for _ in range(2):
        ctx = ctx_for(up, pack, 0.4)
        with ctx() as s:
            t0.generate_batch(up.model, up.tokenizer, BASE_SYSTEM, [rm._PLAIN[0]], 48, lambda: _null())
            heads.append((s.trace.head, s.trace.verify(), len(s.trace.records)))
    return {"identical": heads[0] == heads[1], "verified": heads[0][1], "records": heads[0][2],
            "head": heads[0][0]}


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


async def eval_drift(up, pack, gains: list[float], seeds: int, turns: int,
                     shocks: tuple[int, ...]) -> dict:
    store = Store(DB)                                        # add the steered runs next to the T2 experiment
    out: dict = {}
    for g in gains:
        up.around = ctx_for(up, pack, g)
        rs = [await rm.run_none(up, s, turns, store, arm=f"t0-g{g}", shocks=shocks) for s in range(seeds)]
        up.around = None
        summ = rm.summarize({"x": rs})["x"]
        out[str(g)] = {
            "summary": summ, "per_seed": [r.compliance() for r in rs],
            # every turn (what was said and every check), so the replies behind the numbers are on record
            "conversations": [{"seed": r.seed, "run_id": r.run_id, "turns": r.turns} for r in rs],
        }
        k = summ["by_kind"]
        say(f"  steered gain {g:<4g}: compliant {summ['compliance']:5.1%}  recovery {summ['recovery']:5.1%} "
            f"(plain {k['plain']:5.1%}, tempting {k['tempting']:5.1%})  "
            f"per seed {[round(r.compliance(), 2) for r in rs]}")
    return out


def main() -> int:
    global GAINS
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--skip-drift", action="store_true")
    ap.add_argument("--only-drift", action="store_true",
                    help="run only evaluation 2; writes real_t0_results_drift.json, "
                         "leaving the full results alone")
    ap.add_argument("--drift-gains", default="0.2,0.4,0.6")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--turns", type=int, default=16)
    ap.add_argument("--shocks", default="4,10")
    ap.add_argument("--gsm8k-n", type=int, default=100)
    ap.add_argument("--mmlu-n", type=int, default=300)
    ap.add_argument("--gains", default=",".join(str(g) for g in GAINS), help="steering gains to evaluate")
    args = ap.parse_args()
    GAINS = tuple(float(x) for x in args.gains.split(",") if x)

    say(f"loading {args.model} ...")
    up = HFUpstream.from_pretrained(args.model, served_name=rm.MODEL_ID, max_new_tokens=96)
    up.tokenizer.padding_side = "left"
    n_layers = len(t0.decoder_layers(up.model))
    say(f"loaded; {n_layers} decoder layers; steering band = layers {BAND[0]}..{BAND[1] - 1}")
    pack = derive(up)
    say(f"derived vectors for {sum(pack.get(t0.SIGNAL, l) is not None for l in range(*BAND))} layers "
        f"from {len(DERIVATION_PROMPTS)} held-out prompts")

    result: dict = {"model": args.model, "band": list(BAND), "gains": list(GAINS), "derivation_prompts": len(
        DERIVATION_PROMPTS), "pack_hash": pack.hash()}
    t = time.time()
    out_path = OUT.replace(".json", "_drift.json") if args.only_drift else OUT
    if not args.only_drift:
        say("\n[1] instruction replacement (single turn, 24 held-out plain prompts)")
        result["instruction_replacement"] = eval_instruction_replacement(up, pack)
        say("\n[3] capability retention")
        result["capability"] = eval_capability(up, pack, args.gsm8k_n, args.mmlu_n)
        result["replay"] = replay_check(up, pack)
        say(f"\nreplay identity: {result['replay']}")
    if not args.skip_drift:
        say(f"\n[2] recovery under steering ({args.seeds} conversations x {args.turns} turns)")
        gains = [float(x) for x in args.drift_gains.split(",") if x]
        shocks = tuple(int(x) for x in args.shocks.split(",") if x)
        result["drift"] = asyncio.run(eval_drift(up, pack, gains, args.seeds, args.turns, shocks))
    result["seconds"] = round(time.time() - t)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    say(f"\nsaved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
