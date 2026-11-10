"""Hidden acceptance tests: run by the scorer against a snapshot, never copied into the workspace."""
import pytest


@pytest.fixture(autouse=True)
def clean_state():
    from app import cache, db, http_client

    db.reset()
    cache.clear()
    http_client.set_transport(None)
    yield
    http_client.set_transport(None)
