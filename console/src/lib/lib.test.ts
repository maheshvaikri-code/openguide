import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi } from "./api";
import { diffJson } from "./diff";
import { cellAt, driftBand, driftColor, layoutGrid } from "./heat";
import { excursionStarts, pickAxes, project } from "./projection";
import { clampIndex, correctionIndexes, firstCorrection, parseStates, readingSeries } from "./replay";
import { atOrAbove, parseThresholds } from "./thresholds";
import { hrefFor, parseHash } from "./router";
import type { StateRecord } from "./types";

const st = (turn: number, drift: number, over: Partial<StateRecord> = {}): Record<string, unknown> => ({
  ev: "STATE",
  turn,
  tier_active: "t2",
  invariants: { adherence: { reading: 0.9 - drift, floor: 0.85, violated: false } },
  drift,
  signals_active: {},
  recovery_fired: null,
  validation_failures: [],
  sensor_gaps: [],
  reanchored: false,
  ...over,
});

// ── replay (AC6) ───────────────────────────────────────────────────────────
describe("replay", () => {
  const recs = [st(0, 0), st(1, 0.05), st(2, 0.4, { recovery_fired: "re_anchor" }), st(3, 0.1)];

  it("finds the first correction", () => {
    const { states } = parseStates(recs);
    expect(firstCorrection(states)).toBe(2);
    expect(states[2]?.turn).toBe(2);
    expect(correctionIndexes(states)).toEqual([2]);
  });

  it("returns -1 when nothing was corrected", () => {
    expect(firstCorrection(parseStates([st(0, 0)]).states)).toBe(-1);
  });

  it("ignores malformed and non-STATE records instead of throwing", () => {
    const { states, ignored } = parseStates([st(0, 0), { ev: "TOOL_POLICY" }, { ev: "STATE", turn: "x" }, null as never]);
    expect(states).toHaveLength(1);
    expect(ignored).toBe(3);
  });

  it("handles an empty or missing trace", () => {
    expect(parseStates([]).states).toEqual([]);
    expect(parseStates(undefined).states).toEqual([]);
  });

  it("sorts by turn and exposes null for sensor gaps", () => {
    const gap = st(1, 0, { invariants: { adherence: { reading: null, floor: 0.85, violated: false } } });
    const { states } = parseStates([st(2, 0), gap, st(0, 0)]);
    expect(states.map((s) => s.turn)).toEqual([0, 1, 2]);
    expect(readingSeries(states, "adherence")[1]).toBeNull();
  });

  it("normalises malformed fields instead of passing them to the UI (a crash would blank the page)", () => {
    const odd = {
      ev: "STATE", turn: 0, drift: 0.1,
      invariants: { a: {}, b: { reading: "x", floor: null }, c: null, d: { reading: 0.5, floor: 0.8, violated: "yes" } },
      signals_active: { good: 0.3, bad: "high", worse: null },
      recovery_fired: 7, validation_failures: "oops", sensor_gaps: [1, "ok"], reanchored: "truthy",
    };
    const { states } = parseStates([odd]);
    const s0 = states[0]!;
    expect(s0.invariants["a"]).toEqual({ reading: null, floor: null, violated: false });
    expect(s0.invariants["b"]?.reading).toBeNull();           // a string reading is not a reading
    expect(s0.invariants["c"]).toBeUndefined();               // not an object: dropped
    expect(s0.invariants["d"]).toMatchObject({ reading: 0.5, floor: 0.8, violated: false });
    expect(s0.signals_active).toEqual({ good: 0.3 });
    expect(s0.recovery_fired).toBeNull();
    expect(s0.validation_failures).toEqual([]);
    expect(s0.sensor_gaps).toEqual(["ok"]);
    // every consumer calls .toFixed on these, so they must be real numbers or null
    for (const v of Object.values(s0.invariants)) expect(v.reading === null || typeof v.reading === "number").toBe(true);
  });

  it("clamps scrub indexes", () => {
    expect(clampIndex(-5, 10)).toBe(0);
    expect(clampIndex(99, 10)).toBe(9);
    expect(clampIndex(3.6, 10)).toBe(4);
    expect(clampIndex(5, 0)).toBe(0);
  });
});

// ── projection (AC7) ───────────────────────────────────────────────────────
describe("projection", () => {
  const inv = (a: number, c: number) => ({
    adherence: { reading: a, floor: 0.85, violated: a < 0.85 },
    cesr: { reading: c, floor: 0.8, violated: c < 0.8 },
    tests_gate: { reading: 1, floor: null, violated: false },
  });
  const states = parseStates([
    st(0, 0, { invariants: inv(0.95, 0.9) }),
    st(1, 0.4, { invariants: inv(0.55, 0.5), recovery_fired: "re_anchor" }),
    st(2, 0.45, { invariants: inv(0.5, 0.45) }),
    st(3, 0.0, { invariants: inv(0.95, 0.9) }),
  ]).states;

  it("is deterministic and bounded to 0..1", () => {
    const axes = pickAxes(states);
    const a = project(states, axes, 0.27);
    const b = project(states, pickAxes(states), 0.27);
    expect(a).toEqual(b);
    for (const p of a.points) for (const v of [p.x, p.y, p.z]) expect(v).toBeGreaterThanOrEqual(0), expect(v).toBeLessThanOrEqual(1);
  });

  it("prefers invariants with soft floors", () => {
    expect(pickAxes(states).slice(0, 2).sort()).toEqual(["adherence", "cesr"]);
  });

  it("pads missing axes with drift", () => {
    const only = parseStates([st(0, 0.1)]).states;
    expect(pickAxes(only)).toEqual(["adherence", "drift", "drift2"]);
  });

  it("flags excursions and corrections, and finds where each began", () => {
    const p = project(states, pickAxes(states), 0.27);
    expect(p.points.map((x) => x.excursion)).toEqual([false, true, true, false]);
    expect(p.points[1]?.corrected).toBe(true);
    expect(excursionStarts(p.points)).toEqual([1]);
  });

  it("carries the last reading across a sensor gap and marks the point", () => {
    const gap = parseStates([
      st(0, 0, { invariants: { adherence: { reading: 0.9, floor: 0.85, violated: false } } }),
      st(1, 0, { invariants: { adherence: { reading: null, floor: 0.85, violated: false } } }),
    ]).states;
    const p = project(gap, ["adherence", "drift", "drift2"], 0.27);
    expect(p.points[1]?.x).toBeCloseTo(0.9);
    expect(p.points[1]?.gap).toBe(true);
    expect(p.points[0]?.gap).toBe(false);
  });

  it("derives the safe region from floors", () => {
    const p = project(states, ["adherence", "cesr", "drift"], 0.27);
    expect(p.safe[0]).toEqual([0.85, 1]);
    expect(p.safe[1]).toEqual([0.8, 1]);
    expect(p.safe[2]).toEqual([0, 0.27]);
  });

  it("flags at-or-above the threshold, as the reconciler does", () => {
    const edge = parseStates([st(0, 0.26), st(1, 0.27), st(2, 0.28)]).states;
    expect(project(edge, pickAxes(edge), 0.27).points.map((p) => p.excursion)).toEqual([false, true, true]);
  });

  it("invents no threshold when the contract has none", () => {
    const p = project(states, ["adherence", "cesr", "drift"], null);
    expect(p.points.some((q) => q.excursion)).toBe(false);
    expect(p.safe[2]).toEqual([0, 1]);
  });

  it("does not treat an invariant that merely starts with 'drift' as the drift axis", () => {
    const s2 = parseStates([st(0, 0.9, { invariants: { drift_guard: { reading: 0.2, floor: 0.5, violated: true } } })]).states;
    const p = project(s2, ["drift_guard", "drift", "drift2"], 0.27);
    expect(p.points[0]?.x).toBeCloseTo(0.2);   // the invariant's reading, not the run's drift (0.9)
    expect(p.safe[0]).toEqual([0.5, 1]);
  });

  it("handles an empty run", () => {
    expect(project([], pickAxes([]), null).points).toEqual([]);
  });
});

// ── diff (AC8) ─────────────────────────────────────────────────────────────
describe("diffJson", () => {
  it("reports added, removed and changed paths", () => {
    const d = diffJson(
      { a: 1, b: { c: [1, 2] }, gone: true },
      { a: 2, b: { c: [1, 2, 3] }, fresh: "x" },
    );
    expect(d).toEqual([
      { path: "a", kind: "changed", before: 1, after: 2 },
      { path: "b.c[2]", kind: "added", after: 3 },
      { path: "fresh", kind: "added", after: "x" },
      { path: "gone", kind: "removed", before: true },
    ]);
  });

  it("is empty for equal values and handles type changes", () => {
    expect(diffJson({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] })).toEqual([]);
    expect(diffJson({ a: 1 }, { a: [1] })[0]?.kind).toBe("changed");
    expect(diffJson(null, null)).toEqual([]);
  });
});

// ── heat / layout (AC5) ────────────────────────────────────────────────────
describe("heat", () => {
  it("lays out N cells in a grid wide enough to hold them", () => {
    const l = layoutGrid(10000, 1000, 8, 2);
    expect(l.cols).toBe(100);
    expect(l.rows).toBe(100);
    expect(l.cols * l.rows).toBeGreaterThanOrEqual(10000);
  });

  it("hit-tests cells, gaps and the empty tail", () => {
    const l = layoutGrid(5, 50, 8, 2); // 5 cols, 1 row
    expect(cellAt(l, 5, 0, 0)).toBe(0);
    expect(cellAt(l, 5, 25, 4)).toBe(2);
    expect(cellAt(l, 5, 9, 4)).toBe(-1); // in the gap
    const wide = layoutGrid(3, 50, 8, 2);
    expect(cellAt(wide, 3, 35, 4)).toBe(-1); // past the last cell
    expect(cellAt(wide, 3, -1, 0)).toBe(-1);
  });

  it("bands and colours drift, tolerating bad input", () => {
    expect(driftBand(0)).toBe("healthy");
    expect(driftBand(0.27)).toBe("watch");      // a scale, not a contract threshold
    expect(driftBand(0.3)).toBe("high");
    expect(driftBand(0.6)).toBe("halt");
    expect(driftColor(0)).toMatch(/^rgb\(/);
    expect(driftColor(Number.NaN)).toBe(driftColor(0));
    expect(driftColor(5)).toBe(driftColor(1));
  });
});

// ── thresholds (B1: never draw a contract threshold the contract didn't state) ──
describe("thresholds", () => {
  it("reads the drift threshold and the halt rung from the contract", () => {
    expect(parseThresholds({ recovery: { drift_threshold: 0.05, actions: ["re_anchor", "escalate@0.30", "halt@0.60"] } }))
      .toEqual({ threshold: 0.05, halt: 0.6 });
    expect(parseThresholds({ recovery: { drift_threshold: 0.25, actions: ["re_anchor", "halt@0.55"] } }))
      .toEqual({ threshold: 0.25, halt: 0.55 });
  });

  it("is null, never a default, when the contract doesn't say", () => {
    for (const c of [null, undefined, {}, { recovery: {} }, { recovery: { drift_threshold: "x" } }, [], "s", 3]) {
      expect(parseThresholds(c as never)).toEqual({ threshold: null, halt: null });
    }
    expect(parseThresholds({ recovery: { drift_threshold: 0.3, actions: ["re_anchor"] } }).halt).toBeNull();
  });

  it("uses at-or-above, matching the reconciler", () => {
    expect(atOrAbove(0.27, 0.27)).toBe(true);
    expect(atOrAbove(0.26, 0.27)).toBe(false);
    expect(atOrAbove(1, null)).toBe(false);
  });
});

// ── router ─────────────────────────────────────────────────────────────────
describe("router", () => {
  it("parses pages and params, falling back to the fleet", () => {
    expect(parseHash("")).toEqual({ page: "fleet", param: null });
    expect(parseHash("#/run/demo-governed-sparse")).toEqual({ page: "run", param: "demo-governed-sparse" });
    expect(parseHash("#/contracts/sha256%3Aabc")).toEqual({ page: "contracts", param: "sha256:abc" });
    expect(parseHash("#/nonsense/x").page).toBe("fleet");
    expect(parseHash("#/run/%E0%A4%A").param).toBe("%E0%A4%A"); // malformed escape does not throw
  });

  it("round-trips hrefs", () => {
    expect(parseHash(hrefFor("audit", "a/b c"))).toEqual({ page: "audit", param: "a/b c" });
  });
});

// ── api client (AC13) ──────────────────────────────────────────────────────
const res = (status: number, body: unknown, raw = false) =>
  new Response(raw ? String(body) : JSON.stringify(body), { status });

describe("api", () => {
  it("sends the bearer token when one is set", async () => {
    const f = vi.fn().mockResolvedValue(res(200, { runs: [] }));
    await createApi({ fetchImpl: f, getToken: () => "s3cret" }).runs();
    expect(new Headers((f.mock.calls[0]![1] as RequestInit).headers).get("authorization")).toBe("Bearer s3cret");
  });

  it("reports a 401 as needing a token", async () => {
    const api = createApi({ fetchImpl: vi.fn().mockResolvedValue(res(401, { error: "admin token required" })) });
    await expect(api.runs()).rejects.toMatchObject({ status: 401, needsToken: true });
  });

  it("explains an unreachable proxy", async () => {
    const api = createApi({ fetchImpl: vi.fn().mockRejectedValue(new TypeError("fetch failed")) });
    const err = await api.contracts().catch((e: unknown) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
    expect((err as ApiError).message).toMatch(/Couldn't reach the proxy/);
  });

  it("survives non-JSON error bodies", async () => {
    const api = createApi({ fetchImpl: vi.fn().mockResolvedValue(res(502, "<html>Bad gateway</html>", true)) });
    await expect(api.packs()).rejects.toMatchObject({ status: 502 });
  });

  it("returns validation errors as data, not exceptions", async () => {
    const api = createApi({ fetchImpl: vi.fn().mockResolvedValue(res(422, { ok: false, error: "enforcement_floor must be one of" })) });
    expect(await api.validate({})).toEqual({ ok: false, error: "enforcement_floor must be one of" });
  });

  it("builds the runs query from the filter", async () => {
    const f = vi.fn().mockResolvedValue(res(200, { runs: [] }));
    await createApi({ fetchImpl: f }).runs({ min_drift: 0.27, halted: true, limit: 50 });
    expect(f.mock.calls[0]![0]).toBe("/v1/openguide/runs?min_drift=0.27&halted=true&limit=50");
  });
});
