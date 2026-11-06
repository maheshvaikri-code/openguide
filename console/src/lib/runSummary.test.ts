import { describe, expect, it } from "vitest";
import { parseContractInfo } from "./contractInfo";
import { summarizeRun } from "./runSummary";
import type { StateRecord } from "./types";

const info = parseContractInfo({
  invariants: [
    { id: "brevity", measure: "structural:brevity", floor: 0.9, weight: 0.3 },
    { id: "sign_off", measure: "structural:sign_off", floor: 0.9, weight: 0.5 },
  ],
  recovery: { drift_threshold: 0.1, actions: ["re_anchor"] },
});

const inv = (reading: number | null) => ({ reading, floor: 0.9, violated: reading !== null && reading < 0.9 });
const st = (turn: number, drift: number, brevity: number | null, signOff: number | null, fired: string | null = null,
  gaps: string[] = []): StateRecord => ({
  ev: "STATE", turn, tier_active: "t2", drift, invariants: { brevity: inv(brevity), sign_off: inv(signOff) },
  signals_active: {}, recovery_fired: fired, validation_failures: [], sensor_gaps: gaps, reanchored: Boolean(fired),
});

// turn 0 fine; 1-2 sign-off missed (drift 0.45) with a correction at 1; turn 3 recovers; turn 4 fine
const STATES = [st(0, 0, 1, 1), st(1, 0.45, 1, 0, "re_anchor"), st(2, 0.45, 1, 0), st(3, 0, 1, 1), st(4, 0, 1, 1)];

describe("summarizeRun", () => {
  it("counts the turns at or above the contract's first response gate", () => {
    const s = summarizeRun(STATES, info);
    expect(s.turns).toBe(5);
    expect(s.gate).toBe(0.1);
    expect(s.atOrAbove).toBe(2);                                           // turns 1 and 2
  });

  it("finds the first correction and the turn drift came back below the gate", () => {
    const s = summarizeRun(STATES, info);
    expect(s.firstCorrection).toBe(1);
    expect(s.recoveredAt).toBe(3);
  });

  it("says drift never came back when it didn't", () => {
    const s = summarizeRun([st(0, 0.45, 1, 0, "re_anchor"), st(1, 0.45, 1, 0)], info);
    expect(s.firstCorrection).toBe(0);
    expect(s.recoveredAt).toBeNull();
  });

  it("has no correction or recovery for a clean run", () => {
    const s = summarizeRun([st(0, 0, 1, 1), st(1, 0, 1, 1)], info);
    expect(s).toMatchObject({ atOrAbove: 0, firstCorrection: null, recoveredAt: null });
  });

  it("tallies, per rule, how often it was missed and how low it went", () => {
    const [first, second] = summarizeRun(STATES, info).rules;
    expect(first).toMatchObject({ id: "sign_off", missed: 2, scored: 5, lowest: 0, kind: "deterministic check" });
    expect(second).toMatchObject({ id: "brevity", missed: 0, scored: 5, lowest: 1 });   // most-missed first
  });

  it("counts turns with a missing reading, and does not count them as missed or scored", () => {
    const s = summarizeRun([st(0, 0, 1, null, null, ["sign_off"]), st(1, 0, 1, 1)], info);
    const so = s.rules.find((r) => r.id === "sign_off")!;
    expect(so).toMatchObject({ missed: 0, scored: 1, gaps: 1 });
    expect(s.gapTurns).toBe(1);
  });

  it("makes no gate claim when the contract's gate is unknown, but still tallies the rules", () => {
    const s = summarizeRun(STATES, parseContractInfo(null));
    expect(s).toMatchObject({ gate: null, atOrAbove: null, recoveredAt: null });
    expect(s.firstCorrection).toBe(1);                                       // that is in the trace itself
    expect(s.rules.find((r) => r.id === "sign_off")?.missed).toBe(2);
  });

  it("copes with an empty run", () => {
    expect(summarizeRun([], info)).toMatchObject({ turns: 0, atOrAbove: 0, firstCorrection: null, rules: [] });
  });
});
