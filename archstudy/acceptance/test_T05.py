from app.handlers import reports

from .helpers import make, set_status


def test_daily_totals_counts_and_sums_orders_that_are_not_cancelled():
    make(1, qty=1, unit=100)
    b = make(1, qty=2, unit=100)
    make(2, qty=3, unit=100)
    set_status(b["id"], "cancelled")
    assert reports.daily_totals() == (200, {"count": 2, "total_cents": 400})


def test_daily_totals_with_no_orders_is_zero():
    assert reports.daily_totals() == (200, {"count": 0, "total_cents": 0})
