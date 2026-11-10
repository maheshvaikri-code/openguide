from app.handlers import orders

from .helpers import make


def test_pages_split_the_customers_orders_in_id_order():
    ids = [make(5)["id"] for _ in range(5)]
    make(6)
    status, body = orders.list_orders_page(5, 1, 2)
    assert status == 200 and [o["id"] for o in body["orders"]] == ids[:2]
    assert (body["page"], body["size"], body["total"]) == (1, 2, 5)
    assert [o["id"] for o in orders.list_orders_page(5, 3, 2)[1]["orders"]] == ids[4:]
    assert orders.list_orders_page(5, 4, 2)[1]["orders"] == []
