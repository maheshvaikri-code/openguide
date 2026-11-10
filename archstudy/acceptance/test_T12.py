from app.handlers import orders

from .helpers import make


def test_cancelling_leaves_one_audit_event():
    o = make()
    assert orders.get_audit(o["id"]) == (200, {"events": []})
    orders.cancel_order(o["id"])
    assert orders.get_audit(o["id"]) == (200, {"events": ["cancelled"]})
    orders.cancel_order(o["id"])                       # the rejected second cancel adds nothing
    assert orders.get_audit(o["id"]) == (200, {"events": ["cancelled"]})


def test_audit_for_an_unknown_order_is_404():
    assert orders.get_audit(999) == (404, {"error": "not found"})
