"""Hash-chained run trace: the flight recorder.

head_0 = chash(manifest)
head_i = chash({"prev": head_{i-1}, **record_i})

Same manifest + same recorded events  =>  bit-identical head hash.
Any mutation of any record breaks verify().
"""
from __future__ import annotations
import json
from .canonical import chash, canonical_json


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
