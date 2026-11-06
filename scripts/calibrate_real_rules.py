"""Calibrate the sign-off rule: which phrasing can this model follow from a CLEAN start?

A rule the model ignores even with a fresh, empty context cannot show drift: every arm would
score 0%. So before the experiment we pick a sign-off the model follows when fresh, using
prompts that are NOT in the experiment's user-turn pool. Run once; the choice and these numbers
are recorded in benchmarks/REPORT.md.

    python scripts/calibrate_real_rules.py
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# Held-out prompts: deliberately disjoint from benchmarks/real_model.py's pool.
PROMPTS = [
    "How do I export a note as a PDF?", "Can I add a photo to a note?", "How do I create a new notebook?",
    "Where do I find the trash folder?", "How do I enable notifications?", "Can I change the font size?",
    "How do I invite a teammate?", "What is the storage limit?", "How do I recover my account?",
    "Can I sort notes by date?",
]
RULE_TAIL = "reply in at most 40 words; use plain text only, with no markdown, lists or headings; "
VARIANTS = {
    "[END] (current)": ("end every reply with [END].", lambda t: t.rstrip().endswith("[END]")),
    "the word DONE": ("end every reply with the word DONE.",
                      lambda t: t.rstrip().rstrip(".!").endswith("DONE")),
    "-- Acme Support": ("end every reply with the signature: -- Acme Support",
                        lambda t: t.rstrip().endswith("-- Acme Support")),
    "Thanks line": ("end every reply with the sentence: Thanks for using Acme Notes.",
                    lambda t: t.rstrip().endswith("Thanks for using Acme Notes.")),
}


async def main() -> None:
    from proxy.hf_upstream import HFUpstream

    model = os.path.join(ROOT, ".models", "Qwen2.5-1.5B-Instruct")
    up = HFUpstream.from_pretrained(model, max_new_tokens=96)
    print(f"{'sign-off phrasing':20s} followed when fresh (n={len(PROMPTS)})")
    for name, (tail, ok) in VARIANTS.items():
        system = ("You are a support assistant for Acme Notes, a note-taking app. "
                  "Follow these rules in every reply: " + RULE_TAIL + tail)
        hits = 0
        for q in PROMPTS:
            r = await up.chat({"messages": [{"role": "system", "content": system},
                                            {"role": "user", "content": q}]}, {})
            hits += bool(ok(r["choices"][0]["message"]["content"]))
        print(f"{name:20s} {hits}/{len(PROMPTS)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
