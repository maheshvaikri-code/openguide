"""The shared HTTP client. Every outbound HTTP call goes through here (ADR-003, ADR-005)."""
import json
import urllib.request


class TransientError(Exception):
    """A failure worth retrying (timeout, 5xx)."""


_transport = None


def set_transport(fn):
    """Replace the network call (tests inject a fake)."""
    global _transport
    _transport = fn


def _urllib_transport(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def get_json(url, timeout=5.0):
    return (_transport or _urllib_transport)(url, timeout)
