# ADR-007: Do not evade a boundary dynamically (rule H3)

**Status:** accepted

Do not use `__import__`, `importlib`, `eval` or `exec`, and do not import or access another module's private (underscore) names.
If a boundary is in the way, change the design or ask; do not route around it.

**Why:** ADR-001 to ADR-006 are only worth anything if they cannot be bypassed by a trick that a reader (or a checker) cannot see.
