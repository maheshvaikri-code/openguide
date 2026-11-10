from app.handlers import orders

from .helpers import make


def test_a_note_can_be_stored_read_and_replaced():
    o = make()
    assert orders.get_note(o["id"]) == (200, {"note": None})
    assert orders.put_note(o["id"], "fragile") == (200, {"ok": True})
    assert orders.get_note(o["id"]) == (200, {"note": "fragile"})
    orders.put_note(o["id"], "call first")
    assert orders.get_note(o["id"]) == (200, {"note": "call first"})


def test_notes_for_unknown_orders_are_404():
    assert orders.put_note(999, "x")[0] == 404 and orders.get_note(999)[0] == 404
