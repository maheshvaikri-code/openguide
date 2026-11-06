import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Api } from "../lib/api";
import { ACTION_MEANING, describeRun, detectionRows, explainedDrift, ladderSteps, parseContractInfo, responseGate } from "../lib/contractInfo";
import { parseStates, parseTurns } from "../lib/replay";
import { seriesOf } from "../lib/series";
import type { Json, Run, StateRecord, TraceResponse } from "../lib/types";
import { missedRules } from "../ui/ConversationList";
import { ApiProvider } from "../ui/ApiContext";
import { FleetPage } from "./Fleet";
import { RunPage } from "./Run";

afterEach(() => vi.useRealTimers());
beforeEach(() => { window.location.hash = ""; });

const st = (over: Partial<StateRecord> = {}): StateRecord => ({
  ev: "STATE", turn: 0, tier_active: "t2", drift: 0, invariants: {}, signals_active: {}, recovery_fired: null,
  validation_failures: [], sensor_gaps: [], reanchored: false, ...over,
});
const inv = (reading: number | null, floor: number | null = 0.9) => ({ reading, floor, violated: reading !== null && floor !== null && reading < floor });

// ── hard rules (M2) ────────────────────────────────────────────────────────
describe("hard rules are never shown as passed without a basis", () => {
  const info = parseContractInfo({
    invariants: [
      { id: "tests", measure: "structural:tests_pass", hard: true },
      { id: "judged", measure: "judge:policy", hard: true },
    ],
  });

  it("a hard rule with no reading is 'no reading', not passed", () => {
    const rows = detectionRows(st({ invariants: { tests: inv(null, null) }, sensor_gaps: ["tests"] }), info);
    expect(rows[0]?.status).toBe("no-reading");
  });

  it("a hard rule whose measure the validator never runs is 'not checked'", () => {
    const rows = detectionRows(st({ invariants: { judged: inv(1, null) } }), info);
    expect(rows[0]?.status).toBe("not-checked");
  });

  it("a structural hard rule passes only when it has a reading and no validation failure", () => {
    expect(detectionRows(st({ invariants: { tests: inv(1, null) } }), info)[0]?.status).toBe("met");
    expect(detectionRows(st({ invariants: { tests: inv(1, null) }, validation_failures: ["tests"] }), info)[0]?.status).toBe("missed");
  });

  it("the list of missed rules judges a hard rule by its validation result, not by a floor", () => {
    // reading 0.7 under a 0.9 floor would flag a soft rule, but a hard rule is pass/fail on validation
    const s = st({ invariants: { tests: { reading: 0.7, floor: 0.9, violated: true } } });
    expect(missedRules(s, info)).toEqual([]);
    expect(missedRules(s)).toEqual(["tests"]);                                   // without the contract we only have the flag
    expect(missedRules(st({ validation_failures: ["tests"] }), info)).toEqual(["tests"]);
  });
});

// ── defaults and the fired step (m1, m2) ───────────────────────────────────
describe("what the contract states versus what the compiler defaults", () => {
  it("a rule with no stated weight counts with the schema's default weight of 1", () => {
    const i = parseContractInfo({ invariants: [{ id: "a", measure: "judge:a", floor: 0.8 }] });
    expect(i.rules["a"]?.weight).toBe(1);
    const rows = detectionRows(st({ drift: 0.5, invariants: { a: inv(0.3, 0.8) } }), i);
    expect(explainedDrift(rows)).toBeCloseTo(0.5);                                // 1.0 x (0.8 - 0.3): the breakdown works
  });

  it("a rung with no gate and a contract with no threshold uses the compiler's default of 1, and says so", () => {
    const i = parseContractInfo({ recovery: { actions: ["re_anchor"] } });
    expect(ladderSteps(i, 0.9)[0]).toMatchObject({ gate: 1, defaulted: true, reached: false });
    expect(ladderSteps(i, 1)[0]).toMatchObject({ reached: true });
  });

  it("marks the step that was actually recorded when several are reached, even if the ladder is out of order", () => {
    const i = parseContractInfo({ recovery: { drift_threshold: 0.1, actions: ["halt@0.9", "re_anchor@0.3"] } });
    const steps = ladderSteps(i, 0.95, "re_anchor");
    expect(steps.map((s) => s.reached)).toEqual([true, true]);                    // both gates crossed...
    expect(steps.map((s) => s.fired)).toEqual([false, true]);                     // ...but re_anchor is what was recorded
  });

  it("two rungs with the same action are told apart, and only the last matching one is marked", () => {
    const i = parseContractInfo({ recovery: { actions: ["re_anchor@0.3", "re_anchor@0.5"] } });
    expect(ladderSteps(i, 0.6, "re_anchor").map((s) => s.fired)).toEqual([false, true]);
  });

  it("nothing is marked fired when no action was recorded", () => {
    const i = parseContractInfo({ recovery: { actions: ["re_anchor@0.3"] } });
    expect(ladderSteps(i, 0.6, null).some((s) => s.fired)).toBe(false);
  });

  it("the first response step's own gate is what 'starts responding' means", () => {
    expect(responseGate(parseContractInfo({ recovery: { drift_threshold: 0.1, actions: ["re_anchor@0.3", "halt@0.9"] } }))).toBe(0.3);
    expect(responseGate(parseContractInfo({ recovery: { drift_threshold: 0.1, actions: ["re_anchor"] } }))).toBe(0.1);
    expect(responseGate(parseContractInfo(null))).toBeNull();
  });
});

// ── wording that must match what the code does (M1) ────────────────────────
describe("action wording says what is recorded, not what is enforced", () => {
  it("halt is a flag in the record; the proxy does not stop later requests", () => {
    expect(ACTION_MEANING["halt"]).toMatch(/Marks the run as halted in the record/);
    expect(ACTION_MEANING["halt"]).toMatch(/does not itself stop later requests/);
    expect(ACTION_MEANING["halt"]).not.toMatch(/^Stop the run/);
  });
  it("escalate hands nothing to a person by itself", () => {
    expect(ACTION_MEANING["escalate"]).toMatch(/No hand-off to a person happens by itself/);
  });
  it("re-anchor restates the persona and boundaries, not every rule", () => {
    expect(ACTION_MEANING["re_anchor"]).toMatch(/persona and boundaries/);
  });
  it("a run summary says flagged halted, not stopped", () => {
    const run: Run = { run_id: "r", contract_hash: "h", model: "m", tier: "t2", turns: 3, max_drift: 0.9, recoveries: 0,
      halted: true, verified: true, trace_hash: "t", trace_cas_key: "k", created: "" };
    expect(describeRun(run, null)).toContain("flagged halted in the record");
  });
});

// ── series naming (M5b) ────────────────────────────────────────────────────
describe("series names are not guessed from parameters or dates", () => {
  it("keeps ids whose trailing number is a parameter, version or date", () => {
    for (const id of ["gpt-4", "gpt-3", "run-2024-01-05", "sweep-gain-10", "sweep-gain-5", "claude-3-5", "pr-12", "v2"]) {
      expect(seriesOf(id)).toBe(id);
    }
  });
  it("still strips a seed and a long zero-padded counter", () => {
    expect(seriesOf("real-shock-none-s3")).toBe("real-shock-none");
    expect(seriesOf("arm_s12")).toBe("arm");
    expect(seriesOf("run-000123")).toBe("run");
    expect(seriesOf("live_00004")).toBe("live");
  });
});

// ── parsing (M4, m8) ───────────────────────────────────────────────────────
describe("records the replay uses are not reported as left out", () => {
  it("TURN records are not counted as ignored; unknown ones are", () => {
    const turn = { ev: "TURN", turn: 0, user: "u", output: "o", restated: null, truncated: false };
    const state = { ev: "STATE", turn: 0, drift: 0, invariants: {}, signals_active: {}, recovery_fired: null };
    expect(parseStates([state, turn, turn, turn]).ignored).toBe(0);
    expect(parseStates([state, { ev: "MYSTERY" }, { ev: "TOOL_POLICY" }]).ignored).toBe(2);
  });
  it("a duplicate TURN keeps the first", () => {
    const t = (o: string) => ({ ev: "TURN", turn: 4, user: "u", output: o, restated: null, truncated: false });
    expect(parseTurns([t("first"), t("second")]).get(4)?.output).toBe("first");
  });
});

// ── the Run page (M3, M4, m3, m4) ──────────────────────────────────────────
const CONTRACT: Json = {
  contract: { name: "c", version: "1" },
  identity: { persona: "p", boundaries: ["b"] },
  invariants: [
    { id: "brevity", measure: "structural:brevity", floor: 0.9, weight: 0.3 },
    { id: "tone", measure: "judge:tone", floor: 0.8, weight: 1 },
    { id: "gate", measure: "judge:policy", hard: true },
  ],
  recovery: { drift_threshold: 0.1, actions: ["re_anchor"] },
};
const run = (): Run => ({ run_id: "d", contract_hash: "h", model: "m", tier: "t2", turns: 3, max_drift: 0.2, recoveries: 0,
  halted: false, verified: true, trace_hash: "t", trace_cas_key: "k", created: "" });
const stRec = (turn: number, extra: Record<string, unknown> = {}) => ({
  ev: "STATE", turn, tier_active: "t2", drift: 0, invariants: { brevity: inv(1), tone: inv(1, 0.8) }, signals_active: {},
  recovery_fired: null, validation_failures: [], sensor_gaps: [], reanchored: false, ...extra,
});
const turnRec = (turn: number) => ({ ev: "TURN", turn, user: `question ${turn}`, output: `answer ${turn}`, restated: null, truncated: false });

function apiFor(records: Array<Record<string, unknown>>): Api {
  const trace: TraceResponse = { manifest: {}, head: "h", verified: true, cas_key: "k", records,
    chain: { ok: true, checked: records.length, break_at: null, reason: null } };
  return { health: async () => true, status: async () => ({ auth_required: true }), runs: async () => [run()], run: async () => run(),
    trace: async () => trace, contracts: async () => [], contract: async (h: string) => ({ hash: h, contract: CONTRACT }),
    validate: async () => ({ ok: false, error: "x" }), register: async () => ({ contract_hash: "x" }),
    packs: async () => ({ packs: [], skipped: [] }) } as Api;
}
const showRun = (a: Api) => render(<ApiProvider api={a}><RunPage runId="d" /></ApiProvider>);

describe("the Run page does not mislead", () => {
  it("shows no 'left out of the replay' banner for a run whose text was captured", async () => {
    showRun(apiFor([stRec(0), turnRec(0), stRec(1), turnRec(1), stRec(2), turnRec(2)]));
    await screen.findByLabelText("Details of turn 0");
    expect(screen.queryByText(/not behavioral-state records/)).not.toBeInTheDocument();
  });

  it("says no text was recorded for THIS turn, not that capture is off, when only some turns have text", async () => {
    showRun(apiFor([stRec(0), turnRec(0), stRec(1), stRec(2), turnRec(2)]));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(screen.getByRole("slider", { name: "Replay position" }), { key: "ArrowRight" });
    const panel = screen.getByLabelText("Details of turn 1");
    expect(panel).toHaveTextContent("No text was recorded for this turn");
    expect(panel).not.toHaveTextContent("OPENGUIDE_CAPTURE_CONTENT");
  });

  it("a turn with a missing sensor reading is never listed as 'All met'", async () => {
    showRun(apiFor([stRec(0), stRec(1, { invariants: { brevity: inv(1), tone: inv(null, 0.8) }, sensor_gaps: ["tone"] }), stRec(2)]));
    const list = await screen.findByLabelText("Every turn");
    const rows = within(list).getAllByRole("row");
    expect(rows[2]).toHaveTextContent("No reading: tone");
    expect(rows[2]).not.toHaveTextContent("All met");
    expect(rows[1]).toHaveTextContent("All met");
  });

  it("a missed rule AND a missing reading are both said", async () => {
    showRun(apiFor([stRec(0, { invariants: { brevity: inv(0), tone: inv(null, 0.8) }, sensor_gaps: ["tone"], drift: 0.27 })]));
    const row = within(await screen.findByLabelText("Every turn")).getAllByRole("row")[1]!;
    expect(row).toHaveTextContent("Missed: brevity");
    expect(row).toHaveTextContent("no reading: tone");
  });

  it("a hard rule the validator never runs reads 'Not checked' with a pass-or-fail column", async () => {
    showRun(apiFor([stRec(0, { invariants: { brevity: inv(1), gate: inv(1, null) } })]));
    const table = within(await screen.findByLabelText("Details of turn 0")).getByRole("table", { name: "Rule results for this turn" });
    const row = within(table).getByText("gate").closest("tr")!;
    expect(row).toHaveTextContent("Not checked");
    expect(row).toHaveTextContent("pass or fail");
  });

  it("when the columns don't add up to the recorded drift it says so, without blaming the contract", async () => {
    showRun(apiFor([stRec(0, { drift: 0.77 })]));
    const panel = await screen.findByLabelText("Details of turn 0");
    expect(panel).toHaveTextContent("The columns add up to 0.00, but the recorded drift is 0.77");
    expect(panel).toHaveTextContent("may be missing a default or a rounding");
    expect(panel).not.toHaveTextContent("contract may have changed");
  });

  it("a re-statement prepared without any action is explained, not reported as 'no action'", async () => {
    showRun(apiFor([stRec(0, { reanchored: true })]));
    expect(await screen.findByLabelText("Details of turn 0")).toHaveTextContent("a re-statement was still prepared for the next request");
  });

  it("the current turn is marked in the list for assistive technology", async () => {
    showRun(apiFor([stRec(0), stRec(1)]));
    const rows = within(await screen.findByLabelText("Every turn")).getAllByRole("row");
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(rows[2]).not.toHaveAttribute("aria-current");
  });
});

// ── the Fleet (M5a, M5c, M6) ───────────────────────────────────────────────
const r = (id: string, o: Partial<Run> = {}): Run => ({ run_id: id, contract_hash: "h", model: "m", tier: "t2", turns: 4,
  max_drift: 0.2, recoveries: 0, halted: false, verified: true, trace_hash: "t", trace_cas_key: "k", created: "", ...o });
const ARMS = [r("a-s0"), r("a-s1"), r("b-s0"), r("b-s1")];

function fleetApi(sequence: Run[][]): Api {
  let i = 0;
  return { health: async () => true, status: async () => ({ auth_required: true }),
    runs: async () => sequence[Math.min(i++, sequence.length - 1)]!, run: async () => ARMS[0]!, trace: async () => ({} as never),
    contracts: async () => [], contract: async (h: string) => ({ hash: h, contract: CONTRACT }),
    validate: async () => ({ ok: false, error: "x" }), register: async () => ({ contract_hash: "x" }),
    packs: async () => ({ packs: [], skipped: [] }) } as Api;
}
const showFleet = (a: Api) => render(<ApiProvider api={a}><FleetPage /></ApiProvider>);

describe("the Fleet's series view", () => {
  it("says the figures cover only the matching runs when a filter is on", async () => {
    showFleet(fleetApi([ARMS]));
    await screen.findByLabelText("Series a");
    expect(screen.queryByText(/Filters are on/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Halted runs only"));
    expect(await screen.findByText(/Filters are on, so each series below shows only the runs that match them/)).toBeInTheDocument();
    expect(screen.getByLabelText("Series a")).toHaveTextContent("2 runs shown");
  });

  it("names integrity and arrival in words on a square, not just by outline colour", async () => {
    vi.useFakeTimers();
    const first = [r("a-s0"), r("a-s1", { verified: false }), r("b-s0"), r("b-s1")];
    showFleet(fleetApi([first, [...first, r("a-s2")]]));
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    const a = screen.getByLabelText("Series a");
    expect(within(a).getByRole("button", { name: /^a-s1: .*trace chain broken$/ })).toBeInTheDocument();
    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));                 // a new run arrives
    expect(within(screen.getByLabelText("Series a")).getByRole("button", { name: /^a-s2: .*arrived since you opened this page/ })).toBeInTheDocument();
  });

  it("does not re-decide the layout when live updates change what the runs look like", async () => {
    vi.useFakeTimers();
    showFleet(fleetApi([ARMS, [r("only-1"), r("only-2"), r("only-3")]]));                  // later: no longer several series
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    expect(screen.getByLabelText("Series a")).toBeInTheDocument();
    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
    expect(screen.queryByLabelText("Series a")).not.toBeInTheDocument();                   // the runs really changed...
    expect(screen.getAllByLabelText(/^Series only/)).toHaveLength(3);                       // ...but the layout did not flip to the grid
    expect(document.querySelector("canvas")).toBeNull();
  });
});
