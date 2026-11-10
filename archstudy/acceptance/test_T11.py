from app.handlers import orders

from .helpers import make, set_status


def test_search_returns_orders_with_that_status_in_id_order():
    a, b, c = make(1), make(2), make(3)
    set_status(b["id"], "shipped")
    set_status(c["id"], "shipped")
    status, body = orders.search_orders("shipped")
    assert status == 200 and [o["id"] for o in body["orders"]] == [b["id"], c["id"]]
    assert [o["id"] for o in orders.search_orders("open")[1]["orders"]] == [a["id"]]
    assert orders.search_orders("nothing") == (200, {"orders": []})
