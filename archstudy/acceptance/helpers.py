from app import db
from app.handlers import orders


def make(customer=1, qty=2, unit=500, sku="A-1"):
    status, order = orders.post_order({"customer_id": customer, "sku": sku, "qty": qty, "unit_cents": unit})
    assert status == 201
    return order


def set_status(order_id, status):
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
