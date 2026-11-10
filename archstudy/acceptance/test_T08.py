import pytest
from app.services import pricing


@pytest.mark.parametrize("qty,unit,disc,expected", [
    (1, 1001, 10, 901), (3, 333, 5, 949), (2, 500, 0, 1000),
    (1, 999, 15, 849), (4, 250, 100, 0), (1, 1, 50, 1),
])
def test_totals_round_half_up_to_the_cent(qty, unit, disc, expected):
    assert pricing.total_cents(qty, unit, disc) == expected
