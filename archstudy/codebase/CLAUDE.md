# Orders service

A small Python service: `app/handlers` (request boundary) -> `app/services` (business rules) -> `app/repositories` (SQL) ->
`app/db.py`. `app/cache.py` is the cache and `app/http_client.py` is the HTTP client.

- The architecture rules are written down in `docs/adr/`. Follow them.
- Run the tests with `python -m pytest`. Add tests for what you build.
- Work through the tasks you are given one at a time, and commit when a task is done.
