"""Order persistence."""
from app import db


def create(customer_id, sku, qty, price_cents):
    cur = db.execute(
        "INSERT INTO orders (customer_id, sku, qty, price_cents) VALUES (?, ?, ?, ?)",
        (customer_id, sku, qty, price_cents),
    )
    return cur.lastrowid


def get(order_id):
    row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None
