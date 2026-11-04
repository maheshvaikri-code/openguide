# Data Contract — <dataset / stream> v<X.Y>
<!-- G1 artifact — data design. Author: Data Engineer (skills/data-engineering.md);
     Head of Data co-signs (governance.md). One contract per shared dataset/stream.
     File as docs/data-contracts/<name>.md. -->

**Producer:** <team/service> · **Consumers:** <the ≥1 that depend on it> · **Owner:** <name>
**Status:** proposed | active | deprecated · **SLA:** freshness <…>, availability <…>

## Schema (the promise)
| Field | Type | Nullable | Meaning | PII? |
|-------|------|----------|---------|------|
| … | … | … | … | … |

## Semantics
Grain: <one row / message = …> · Keys: <…> · Units + timezone: <…> ·
Late / duplicate / out-of-order policy: <…>

## Quality guarantees
<row-count bounds · null thresholds · referential + range checks — and where enforced>

## Change policy
Breaking changes → a new version + a migration window; consumers notified. A silent
schema change that breaks a consumer is a **contract violation**, not a hotfix.

## Lineage & retention
Upstream: <…> · Downstream (who breaks if this changes): <…> · Retention: <…>
(one definition per entity — `standards/governance.md`).
