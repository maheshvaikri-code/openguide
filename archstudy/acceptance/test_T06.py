from app.handlers import orders

from .helpers import make


def test_cancel_order_sets_the_status_once():
    o = make()
    status, body = orders.cancel_order(o["id"])
    assert status == 200 and body["status"] == "cancelled" and body["id"] == o["id"]
    assert orders.cancel_order(o["id"]) == (409, {"error": "already cancelled"})


def test_cancel_unknown_order_is_404():
    assert orders.cancel_order(999) == (404, {"error": "not found"})
