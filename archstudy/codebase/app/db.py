"""The database connection. Only repositories call into this module (ADR-001, ADR-006)."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
);
"""

QUERY_COUNT = 0
_conn = None


def connection():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(":memory:", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def reset():
    """Start from an empty database (used by tests)."""
    global _conn, QUERY_COUNT
    if _conn is not None:
        _conn.close()
    _conn = None
    QUERY_COUNT = 0


def execute(sql, params=()):
    global QUERY_COUNT
    QUERY_COUNT += 1
    return connection().execute(sql, params)


def query_count():
    return QUERY_COUNT
