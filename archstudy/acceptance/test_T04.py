from app import db
from app.handlers import orders

from .helpers import make


def test_repeated_listing_does_not_query_the_database_again():
    make(7)
    first = orders.list_orders(7)
    n = db.query_count()
    assert orders.list_orders(7) == first
    assert db.query_count() == n


def test_a_new_order_shows_up_in_the_next_listing():
    make(7)
    assert len(orders.list_orders(7)[1]["orders"]) == 1
    make(7)
    assert len(orders.list_orders(7)[1]["orders"]) == 2


def test_other_customers_are_unaffected():
    make(7)
    make(8)
    assert [o["customer_id"] for o in orders.list_orders(8)[1]["orders"]] == [8]
    assert [o["customer_id"] for o in orders.list_orders(7)[1]["orders"]] == [7]
