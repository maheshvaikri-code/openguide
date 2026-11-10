"""Order endpoints. Each handler returns (status, body)."""
from app.services import orders as svc


def post_order(body):
    order = svc.create_order(body["customer_id"], body["sku"], body["qty"], body["unit_cents"],
                             body.get("discount_pct", 0))
    return 201, order
