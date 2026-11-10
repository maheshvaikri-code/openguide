import pytest
from app import db
from app.handlers import orders


@pytest.mark.parametrize("body", [
    {"customer_id": 1, "sku": "A", "qty": 0, "unit_cents": 100},
    {"customer_id": 1, "sku": "A", "qty": -2, "unit_cents": 100},
    {"customer_id": 1, "sku": "A", "qty": 1.5, "unit_cents": 100},
    {"customer_id": 1, "sku": "A", "qty": "3", "unit_cents": 100},
    {"customer_id": 1, "sku": "A", "qty": 1, "unit_cents": -1},
])
def test_bad_input_is_rejected_and_nothing_is_created(body):
    assert orders.post_order(body) == (422, {"error": "invalid order"})
    assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_good_input_still_works():
    assert orders.post_order({"customer_id": 1, "sku": "A", "qty": 1, "unit_cents": 0})[0] == 201
