"""Order business logic."""
from app.repositories import orders as repo
from app.services import pricing


def create_order(customer_id, sku, qty, unit_cents, discount_pct=0):
    total = pricing.total_cents(qty, unit_cents, discount_pct)
    order_id = repo.create(customer_id, sku, qty, total)
    return repo.get(order_id)
