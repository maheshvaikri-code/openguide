import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def clean_state():
    from app import cache, db

    db.reset()
    cache.clear()
    yield
