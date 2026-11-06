import { describe, expect, it } from "vitest";
import { ACTION_MEANING, describeRun, detectionRows, explainedDrift, ladderSteps, measureKind, parseContractInfo } from "./contractInfo";
import { groupRuns, seriesOf, shouldGroup } from "./series";
import { parseSteers, parseTurns } from "./replay";
import type { Json, Run, StateRecord } from "./types";

const contract = (extra: Record<string, Json> = {}): Json => ({
  contract: { name: "support-plain-brief", version: "0.1.0" },
  identity: { persona: "concise assistant", boundaries: ["reply in at most 40 words", "end every reply with [END]"] },
  invariants: [
    { id: "brevity", measure: "structural:brevity", floor: 0.9, weight: 0.3 },
    { id: "sign_off", measure: "structural:sign_off", floor: 0.9, weight: 0.5 },
    { id: "tests_gate", measure: "structural:tests_pass", hard: true },
    { id: "tone", measure: "judge:tone", floor: 0.8, weight: 1.0 },
  ],
  recovery: { drift_threshold: 0.1, actions: ["re_anchor", "escalate@0.6", "halt@0.95"] },
  ...extra,
});

const state = (over: Partial<StateRecord> = {}): StateRecord => ({
  ev: "STATE", turn: 3, tier_active: "t2", drift: 0.45,
  invariants: {
    brevity: { reading: 1, floor: 0.9, violated: false },
    sign_off: { reading: 0, floor: 0.9, violated: true },
    tests_gate: { reading: 1, floor: null, violated: false },
    tone: { reading: null, floor: 0.8, violated: false },
  },
  signals_active: {}, recovery_fired: "re_anchor", validation_failures: [], sensor_gaps: ["tone"], reanchored: true, ...over,
});

describe("parseContractInfo", () => {
  it("reads rules, boundaries, persona, ladder and threshold", () => {
    const info = parseContractInfo(contract());
    expect(info.threshold).toBe(0.1);
    expect(info.persona).toBe("concise assistant");
    expect(info.boundaries).toEqual(["reply in at most 40 words", "end every reply with [END]"]);
    expect(info.rules["sign_off"]).toEqual({ id: "sign_off", measure: "structural:sign_off", floor: 0.9, weight: 0.5, hard: false });
    expect(info.rules["tests_gate"]?.hard).toBe(true);
    expect(info.ladder).toEqual([{ action: "re_anchor", gate: null }, { action: "escalate", gate: 0.6 }, { action: "halt", gate: 0.95 }]);
  });

  it("never throws or guesses on missing or odd input", () => {
    for (const c of [null, undefined, {}, [], "x", 3, { invariants: "no", identity: 5, recovery: [] }]) {
      const info = parseContractInfo(c as never);
      expect(info.rules).toEqual({});
      expect(info.boundaries).toEqual([]);
      expect(info.ladder).toEqual([]);
      expect(info.threshold).toBeNull();
    }
    expect(parseContractInfo({ invariants: [{ id: 5 }, null, { measure: "x" }, { id: "ok", floor: "high" }] }).rules)
      .toEqual({ ok: { id: "ok", measure: null, floor: null, weight: 1, hard: false } });    // the schema's default weight
  });
});

describe("detectionRows (what was detected on one turn)", () => {
  const info = parseContractInfo(contract());

  it("says met / missed / no reading / hard check, with the drift each rule added", () => {
    const rows = detectionRows(state(), info);
    const by = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(by["brevity"]).toMatchObject({ status: "met", contribution: 0, kind: "deterministic check" });
    expect(by["sign_off"]).toMatchObject({ status: "missed", weight: 0.5 });
    expect(by["sign_off"]?.contribution).toBeCloseTo(0.45);                 // 0.5 x (0.9 - 0)
    expect(by["tone"]).toMatchObject({ status: "no-reading", contribution: null, kind: "LLM judge" });
    expect(by["tests_gate"]).toMatchObject({ status: "met", hard: true, contribution: null });
  });

  it("explains the recorded drift: the contributions sum to it", () => {
    expect(explainedDrift(detectionRows(state(), info))).toBeCloseTo(0.45);
  });

  it("clips the explained drift to 1, as the reconciler does", () => {
    const rows = detectionRows(state({ invariants: { a: { reading: 0, floor: 1, violated: true } } }),
      parseContractInfo({ invariants: [{ id: "a", measure: "judge:a", floor: 1, weight: 5 }] }));
    expect(explainedDrift(rows)).toBe(1);
  });

  it("a failed hard check is shown as missed", () => {
    const rows = detectionRows(state({ validation_failures: ["tests_gate"] }), info);
    expect(rows.find((r) => r.id === "tests_gate")?.status).toBe("missed");
  });

  it("works from the trace alone when the contract can't be read (no weights, no measure kinds)", () => {
    const rows = detectionRows(state(), parseContractInfo(null));
    const so = rows.find((r) => r.id === "sign_off")!;
    expect(so).toMatchObject({ status: "missed", weight: null, contribution: null, kind: null });
    expect(so.shortfall).toBeCloseTo(0.9);                                    // still shows how far it fell short
    expect(explainedDrift(rows)).toBeNull();                                  // can't claim the arithmetic
  });

  it("an invariant with no floor is not scored", () => {
    const rows = detectionRows(state({ invariants: { x: { reading: 0.5, floor: null, violated: false } } }), parseContractInfo(null));
    expect(rows[0]?.status).toBe("not-scored");
  });
});

describe("ladder", () => {
  const info = parseContractInfo(contract());
  it("marks every rung the drift reached, using the contract's own gates", () => {
    expect(ladderSteps(info, 0.05).map((s) => s.reached)).toEqual([false, false, false]);
    expect(ladderSteps(info, 0.45).map((s) => [s.action, s.gate, s.reached])).toEqual([
      ["re_anchor", 0.1, true], ["escalate", 0.6, false], ["halt", 0.95, false]]);
    expect(ladderSteps(info, 0.95).every((s) => s.reached)).toBe(true);          // at-or-above, like the reconciler
  });
  it("a plain-English meaning exists for each action, and unknown actions are not invented", () => {
    for (const a of ["re_anchor", "escalate", "halt"]) expect(ACTION_MEANING[a]).toBeTruthy();
    expect(ACTION_MEANING["mystery"]).toBeUndefined();
  });
});

describe("measureKind", () => {
  it("names the kind of sensor in plain words", () => {
    expect(measureKind("structural:x")).toBe("deterministic check");
    expect(measureKind("judge:x")).toBe("LLM judge");
    expect(measureKind("probe:x")).toBe("activation probe");
    expect(measureKind("external:x")).toBe("external signal");
    expect(measureKind("weird:x")).toBe("custom measure");
    expect(measureKind(null)).toBeNull();
  });
});

describe("describeRun", () => {
  const run = (o: Partial<Run> = {}): Run => ({
    run_id: "r", contract_hash: "h", model: "m", tier: "t2", turns: 16, max_drift: 0.45, recoveries: 3,
    halted: false, verified: true, trace_hash: "t", trace_cas_key: "k", created: "", ...o,
  });
  it("compares the peak with the contract's own threshold", () => {
    expect(describeRun(run(), 0.1)).toContain("at or above this contract's threshold of 0.1");
    expect(describeRun(run({ max_drift: 0.05 }), 0.1)).toContain("below this contract's threshold of 0.1");
  });
  it("makes no threshold claim when none is known", () => {
    expect(describeRun(run(), null)).not.toMatch(/threshold/);
  });
  it("counts corrections and mentions a halt", () => {
    expect(describeRun(run({ recoveries: 1 }), null)).toContain("1 correction");
    expect(describeRun(run({ recoveries: 0 }), null)).toContain("No correction");
    expect(describeRun(run({ halted: true }), null)).toContain("halted");
  });
});

describe("series (grouping runs into experiment arms)", () => {
  it("strips a trailing seed or counter so arms group together", () => {
    expect(seriesOf("real-shock-none-s3")).toBe("real-shock-none");
    expect(seriesOf("real-t0-g0.05-s1")).toBe("real-t0-g0.05");
    expect(seriesOf("run-000123")).toBe("run");
    expect(seriesOf("live_00004")).toBe("live");
    expect(seriesOf("demo-governed-sparse")).toBe("demo-governed-sparse");
    expect(seriesOf("7")).toBe("7");                                              // never returns an empty name
  });

  const mk = (id: string, drift: number, o: Partial<Run> = {}): Run => ({
    run_id: id, contract_hash: "h", model: "m", tier: "t2", turns: 10, max_drift: drift, recoveries: 0,
    halted: false, verified: true, trace_hash: "t", trace_cas_key: "k", created: "", ...o });

  it("summarises each series", () => {
    const g = groupRuns([mk("a-s0", 0.2), mk("a-s1", 0.6, { halted: true, recoveries: 2 }), mk("b-s0", 0.1, { verified: false })]);
    expect(g.map((x) => x.name)).toEqual(["a", "b"]);
    expect(g[0]).toMatchObject({ count: 2, halted: 1, corrected: 1 });
    expect(g[0]?.meanPeak).toBeCloseTo(0.4);
    expect(g[1]).toMatchObject({ count: 1, broken: 1 });
  });

  it("only groups when there are at least two series with at least two runs", () => {
    const two = groupRuns([mk("a-s0", 0), mk("a-s1", 0), mk("b-s0", 0), mk("b-s1", 0)]);
    expect(shouldGroup(two)).toBe(true);
    expect(shouldGroup(groupRuns([mk("a-s0", 0), mk("a-s1", 0), mk("solo", 0)]))).toBe(false);
    expect(shouldGroup(groupRuns([]))).toBe(false);
  });
});

describe("parseTurns", () => {
  it("keeps well-formed TURN records by turn and drops the rest", () => {
    const t = parseTurns([
      { ev: "STATE", turn: 0 },
      { ev: "TURN", turn: 0, user: "hi", output: "hello", restated: null, truncated: false },
      { ev: "TURN", turn: 1, user: "q", output: "a", restated: "re-state", truncated: true },
      { ev: "TURN", turn: "x" }, { ev: "TURN", turn: 2, user: 5 }, null as never,
    ]);
    expect([...t.keys()]).toEqual([0, 1]);
    expect(t.get(1)).toEqual({ ev: "TURN", turn: 1, user: "q", output: "a", restated: "re-state", truncated: true });
  });
  it("is empty for a trace that captured no content", () => {
    expect(parseTurns([]).size).toBe(0);
    expect(parseTurns(undefined).size).toBe(0);
  });
});

describe("parseSteers", () => {
  const steer = { ev: "STEER", turn: 2, gain: 0.05, band: [10, 19], pack_hash: "sha256:p" };

  it("reads which turns had activation steering, at what gain and over which layers", () => {
    const m = parseSteers([{ ev: "STATE", turn: 1 }, steer]);
    expect(m.size).toBe(1);
    expect(m.get(2)).toEqual({ ev: "STEER", turn: 2, gain: 0.05, band: [10, 19], pack_hash: "sha256:p" });
  });

  it("is empty when nothing was steered, and never throws on odd input", () => {
    expect(parseSteers([]).size).toBe(0);
    expect(parseSteers(undefined).size).toBe(0);
    for (const bad of [
      { ev: "STEER", turn: "2", gain: 0.05, band: [10, 19] },        // turn is not a number
      { ev: "STEER", turn: 2, gain: "high", band: [10, 19] },        // gain is not a number
      { ev: "STEER", turn: 2, gain: 0.05, band: [10] },              // band is not a pair
      { ev: "STEER", turn: 2, gain: 0.05, band: [19, 10] },          // band is backwards
      { ev: "STEER", turn: 2, gain: 0.05, band: ["a", "b"] },
      { ev: "STEER", turn: 2, gain: -1, band: [10, 19] },            // a gain is above zero
    ]) expect(parseSteers([bad as Record<string, unknown>]).size).toBe(0);
  });

  it("leaves out a steering record whose turn was never scored", () => {
    expect(parseSteers([{ ...steer, scored: false }]).size).toBe(0);
    expect(parseSteers([{ ...steer, scored: true }]).size).toBe(1);
  });

  it("keeps the first record for a turn", () => {
    const m = parseSteers([steer, { ...steer, gain: 0.1 }]);
    expect(m.get(2)?.gain).toBe(0.05);
  });
});
