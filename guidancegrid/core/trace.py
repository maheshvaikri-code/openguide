"""Hash-chained run trace: the flight recorder.

head_0 = chash(manifest)
head_i = chash({"prev": head_{i-1}, **record_i})

Same manifest + same recorded events  =>  bit-identical head hash.
Any mutation of any record breaks verify().
"""
from __future__ import annotations

import json

from .canonical import canonical_json, chash

# Captured message text is clipped so one huge message cannot bloat a hash-chained trace.
MAX_CAPTURE_CHARS = 8000


def turn_event(turn: int, user: str, output: str, restated: str | None = None) -> dict:
    """A TURN record: what the user said this turn, what the model replied, and which re-anchor (if any)
    was sent with the request. Opt-in: traces hold behavioral state only unless a caller captures content.
    It is appended after the turn's STATE and rides in the same hash chain."""
    parts = [user, output] + ([restated] if restated is not None else [])
    return {
        "ev": "TURN", "turn": turn,
        "user": user[:MAX_CAPTURE_CHARS], "output": output[:MAX_CAPTURE_CHARS],
        "restated": restated[:MAX_CAPTURE_CHARS] if restated is not None else None,
        "truncated": any(len(p) > MAX_CAPTURE_CHARS for p in parts),
    }


class Trace:
    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.genesis = chash(manifest)
        self.head = self.genesis
        self.records: list[dict] = []

    def append(self, record: dict) -> str:
        rec = {"prev": self.head, **record}
        self.head = chash(rec)
        self.records.append(rec)
        return self.head

    def verify(self) -> bool:
        head = self.genesis
        for rec in self.records:
            if rec.get("prev") != head:
                return False
            head = chash(rec)
        return head == self.head

    # ── persistence ──────────────────────────────────────────────────
    def to_json(self) -> str:
        return json.dumps(
            {"manifest": self.manifest, "head": self.head, "records": self.records}
        )

    @classmethod
    def from_json(cls, s: str) -> "Trace":
        data = json.loads(s)
        t = cls(data["manifest"])
        t.records = data["records"]
        t.head = data["head"]
        return t

    def canonical(self) -> str:
        return canonical_json({"manifest": self.manifest, "records": self.records})
