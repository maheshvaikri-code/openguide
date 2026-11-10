# ADR-004: No new third-party libraries without approval (rule V4)

**Status:** accepted

The application uses the Python standard library. The only approved third-party package is `redis`, and only in `app/cache.py`
(ADR-002). Anything else needs an approval recorded in a new ADR before it is imported.

**Why:** each dependency is a supply-chain and maintenance cost the team has to accept deliberately.

**What to do instead:** use the standard library, or ask for approval and record it first.
