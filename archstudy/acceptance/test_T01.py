from app.handlers import orders

from .helpers import make


def test_get_order_returns_the_orders_columns():
    o = make(customer=4, qty=3, unit=100, sku="Z")
    status, body = orders.get_order(o["id"])
    assert status == 200
    assert body == {
        "id": o["id"], "customer_id": 4, "sku": "Z", "qty": 3, "price_cents": 300, "status": "open",
    }


def test_get_order_unknown_is_404():
    assert orders.get_order(999) == (404, {"error": "not found"})
