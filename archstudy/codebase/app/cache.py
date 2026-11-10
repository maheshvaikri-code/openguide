"""The only module that talks to Redis (ADR-002).

Callers use get/set/delete_prefix. This in-process store stands in for a Redis client;
swapping it in changes only this file.
"""
try:
    import redis  # approved here and nowhere else
except ImportError:  # a bare host without the package still runs
    redis = None

_store = {}


def get(key):
    return _store.get(key)


def set(key, value):  # noqa: A001 - the cache API deliberately mirrors the Redis verbs
    _store[key] = value


def delete_prefix(prefix):
    for key in [k for k in _store if k.startswith(prefix)]:
        del _store[key]


def clear():
    _store.clear()
