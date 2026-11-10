# ADR-006: SQL runs only in repositories (rule H2)

**Status:** accepted

`sqlite3` is imported only by `app/db.py`, and SQL is executed (`execute`, `executemany`, `executescript`, `cursor`) only in
`app/repositories/` and `app/db.py`. Services and handlers never run a query, even through a connection they were handed.

**Why:** ADR-001 only holds if there is no other path to the database than a repository.
