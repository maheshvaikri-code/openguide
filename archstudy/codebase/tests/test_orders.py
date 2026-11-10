from app.handlers import orders


def test_post_order_creates_an_open_order_with_its_total():
    status, order = orders.post_order({"customer_id": 1, "sku": "A-1", "qty": 2, "unit_cents": 500})
    assert status == 201
    assert order["status"] == "open" and order["price_cents"] == 1000 and order["id"] == 1
