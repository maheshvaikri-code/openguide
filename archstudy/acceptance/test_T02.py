from app.handlers import orders

from .helpers import make


def test_list_orders_returns_only_that_customers_orders_in_id_order():
    a, b, c = make(1), make(2), make(1)
    status, body = orders.list_orders(1)
    assert status == 200 and [o["id"] for o in body["orders"]] == [a["id"], c["id"]]
    assert orders.list_orders(2)[1]["orders"][0]["id"] == b["id"]


def test_list_orders_for_a_customer_without_orders_is_empty():
    assert orders.list_orders(77) == (200, {"orders": []})
