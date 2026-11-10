import pytest
from app import http_client
from app.services import customers


def flaky(failures, result=None):
    calls = {"n": 0}

    def transport(url, timeout):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise http_client.TransientError("boom")
        return result or {"id": 1}

    return transport, calls


def test_a_lookup_succeeds_after_two_transient_failures():
    transport, calls = flaky(2, {"id": 1, "name": "Ada"})
    http_client.set_transport(transport)
    assert customers.lookup_customer(1) == {"id": 1, "name": "Ada"}
    assert calls["n"] == 3


def test_a_lookup_gives_up_after_three_attempts_and_reraises():
    transport, calls = flaky(99)
    http_client.set_transport(transport)
    with pytest.raises(http_client.TransientError):
        customers.lookup_customer(1)
    assert calls["n"] == 3


def test_a_healthy_lookup_makes_one_call():
    transport, calls = flaky(0)
    http_client.set_transport(transport)
    customers.lookup_customer(1)
    assert calls["n"] == 1


def test_other_errors_are_not_retried():
    calls = {"n": 0}

    def transport(url, timeout):
        calls["n"] += 1
        raise ValueError("bad payload")

    http_client.set_transport(transport)
    with pytest.raises(ValueError):
        customers.lookup_customer(1)
    assert calls["n"] == 1
