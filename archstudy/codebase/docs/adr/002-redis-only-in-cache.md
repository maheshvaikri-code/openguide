# ADR-002: Only app/cache.py talks to Redis (rule V2)

**Status:** accepted

The `redis` package is imported in exactly one module, `app/cache.py`. Everything else caches through that module's functions
(`get`, `set`, `delete_prefix`). Services call the cache; handlers do not.

**Why:** one place owns the connection, the key naming and the invalidation. A Redis call scattered through handlers cannot be
audited, invalidated consistently or replaced.

**What to do instead:** add the caching to the service that owns the data, using `app.cache`, and invalidate it where the data
changes.
