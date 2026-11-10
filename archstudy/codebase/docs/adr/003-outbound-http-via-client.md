# ADR-003: All outbound HTTP goes through app/http_client.py (rule V3)

**Status:** accepted

Calls to other services use the shared client in `app/http_client.py` (timeouts, retries, error types and test doubles live
there). No other module imports an HTTP library (`requests`, `httpx`, `aiohttp`, `urllib3`, `urllib.request`).

**Why:** timeouts, retry policy and failure handling must be the same everywhere and testable in one place.

**What to do instead:** add the behaviour you need (for example retries) to `app/http_client.py` and call it from the service.
