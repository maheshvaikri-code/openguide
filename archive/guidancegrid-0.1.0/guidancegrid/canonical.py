"""Canonical encoding and content addressing.

Every hashable object in GuidanceGrid (specs, fields, packs, trace records)
passes through one canonical JSON encoding so that hash(obj) is stable
across platforms, dict orderings, and float repr quirks.
"""
import hashlib
import json


def _canon(obj):
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        # 9 significant digits: stable across float32 round-trips
        return float(f"{obj:.9g}")
    if isinstance(obj, dict):
        return {str(k): _canon(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    raise TypeError(f"non-canonical type: {type(obj)}")


def canonical_json(obj) -> str:
    return json.dumps(_canon(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def chash(obj) -> str:
    """Content hash of any canonical-encodable object."""
    return "sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def bhash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
