# Stack Compatibility Manifest — <product> v<X.Y.Z>
<!-- G6 artifact. Filed in the PRODUCT repo as docs/releases/stack-v<X.Y.Z>.md
     (or stack.lock). One manifest per product release. Topology: ADR-003. -->

**Product:** <openhawk> v<X.Y.Z> · **Certified:** <YYYY-MM-DD> · **By:** Release Manager

## Certified stack (the bill of materials)

| Component | Repo | Pinned version | Commit / tag | Notes |
|-----------|------|----------------|--------------|-------|
| Governance | `doctrine` | vA.B.C | <tag/sha> | law + tooling |
| Runtime | `maple-oss` | vD.E.F | <tag/sha> | AGPL; opt-in |
| Product | `<openhawk>` | vX.Y.Z | <tag/sha> | this release |

Dependency direction (ADR-003): product → {doctrine, maple}; doctrine ⟂ maple. No cycles.
If a pin is a range, the lockfile records the exact resolved version.

## Family-gate evidence (required — no evidence, no promotion)

- [ ] Doctrine↔MAPLE family smoke passed against these exact pins
      (the shape in `integrations/maple.md`). Paste the real result:
      ```
      <SMOKE: PASS output>
      ```
- [ ] The product's own gate suite green against these pins.
- [ ] `doctrine_verify` (consumer mode) green in the product repo: lint + state.
- [ ] AGPL obligation acknowledged for this release (MAPLE is AGPL; see the
      product brief's `Workforce runtime: maple`).

## Compatibility notes

- Known-good: <what this combination is verified to do>.
- Known-incompatible / caveats: <e.g., maple < vD needs the older adapter; a
  doctrine bump that changed the protocol vocabulary requires a maple bump>.
- Rollback: the previous certified stack is <product v(X.Y.Z-1) manifest link> —
  roll the whole stack, not one component, unless a note says a component is
  independently safe.

## Sign-off

Release Manager: <name/date>. The family gate is passed only when every box above
is checked with real evidence. Promotion without a green manifest is forbidden
(ADR-003; `standards/merge-and-promotion.md` on enterprise-profile products).
