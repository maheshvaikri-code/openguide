"""Order pricing."""


def total_cents(qty, unit_cents, discount_pct=0):
    gross = qty * unit_cents
    return int(gross * (100 - discount_pct) / 100)
