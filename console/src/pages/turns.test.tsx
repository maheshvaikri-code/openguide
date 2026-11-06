import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { Api } from "../lib/api";
import type { Json, Run, TraceResponse } from "../lib/types";
import { ApiProvider } from "../ui/ApiContext";
import { RunPage } from "./Run";

const CONTRACT: Json = {
  contract: { name: "support-plain-brief", version: "0.1.0" },
  identity: { persona: "concise plain-text support assistant", boundaries: ["reply in at most 40 words", "end every reply with [END]"] },
  invariants: [
    { id: "brevity", measure: "structural:brevity", floor: 0.9, weight: 0.3 },
    { id: "sign_off", measure: "structural:sign_off", floor: 0.9, weight: 0.5 },
  ],
  recovery: { drift_threshold: 0.1, actions: ["re_anchor", "escalate@0.6", "halt@0.95"] },
};

const run = (): Run => ({
  run_id: "demo", contract_hash: "sha256:c", model: "local:qwen", tier: "t2", turns: 3, max_drift: 0.45, recoveries: 1,
  halted: false, verified: true, trace_hash: "sha256:t", trace_cas_key: "k", created: "",
});

const inv = (brevity: number, signOff: number) => ({
  brevity: { reading: brevity, floor: 0.9, violated: brevity < 0.9 },
  sign_off: { reading: signOff, floor: 0.9, violated: signOff < 0.9 },
});
const state = (turn: number, drift: number, i: Record<string, unknown>, fired: string | null = null) => ({
  ev: "STATE", turn, tier_active: "t2", drift, invariants: i, signals_active: {}, recovery_fired: fired,
  validation_failures: [], sensor_gaps: [], reanchored: Boolean(fired),
});

const STATES = [state(0, 0, inv(1, 1)), state(1, 0.45, inv(1, 0), "re_anchor"), state(2, 0, inv(1, 1))];
const TURNS = [
  { ev: "TURN", turn: 0, user: "How do I reset my password?", output: "Click Forgot Password. [END]", restated: null, truncated: false },
  { ev: "TURN", turn: 1, user: "Can I use the app offline?", output: "Yes, offline mode caches your notes and syncs later.", restated: null, truncated: false },
  { ev: "TURN", turn: 2, user: "How do I rename a notebook?", output: "Long-press the title and rename it. [END]", restated: "[contract:anchor] Boundaries: reply in at most 40 words; end every reply with [END].", truncated: false },
];

function api(records: Array<Record<string, unknown>>, contract: Json | null = CONTRACT): Api {
  const trace: TraceResponse = {
    manifest: { model: "local:qwen" }, head: "sha256:h", verified: true, cas_key: "k", records,
    chain: { ok: true, checked: records.length, break_at: null, reason: null },
  };
  return {
    health: async () => true, status: async () => ({ auth_required: true }),
    runs: async () => [run()], run: async () => run(), trace: async () => trace,
    contracts: async () => [], contract: async (hash: string) => {
      if (contract === null) throw new Error("gone");
      return { hash, contract };
    },
    validate: async () => ({ ok: false, error: "n/a" }), register: async () => ({ contract_hash: "x" }),
    packs: async () => ({ packs: [], skipped: [] }),
  } as Api;
}
const withContent = [STATES[0]!, TURNS[0]!, STATES[1]!, TURNS[1]!, STATES[2]!, TURNS[2]!] as Array<Record<string, unknown>>;
const stateOnly = STATES as Array<Record<string, unknown>>;
const show = (a: Api) => render(<ApiProvider api={a}><RunPage runId="demo" /></ApiProvider>);
const slider = () => screen.getByRole("slider", { name: "Replay position" });

beforeEach(() => { window.location.hash = ""; });

describe("what was said", () => {
  it("shows the user's message and the model's reply for the selected turn", async () => {
    show(api(withContent));
    const panel = await screen.findByLabelText("Details of turn 0");
    expect(within(panel).getByText("How do I reset my password?")).toBeInTheDocument();
    expect(within(panel).getByText("Click Forgot Password. [END]")).toBeInTheDocument();
    expect(within(panel).queryByText(/re-stated to the model/)).not.toBeInTheDocument();   // nothing was restated on turn 0
  });

  it("shows the rules that were re-stated with a request, on the turn that carried them", async () => {
    show(api(withContent));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "End" });                                          // turn 2
    const panel = screen.getByLabelText("Details of turn 2");
    expect(within(panel).getByText("Persona and boundaries re-stated to the model with this request")).toBeInTheDocument();
    expect(within(panel).getByText(/Boundaries: reply in at most 40 words/)).toBeInTheDocument();
  });

  it("says plainly why there is no text when content wasn't captured, and still shows the sensor results", async () => {
    show(api(stateOnly));
    const panel = await screen.findByLabelText("Details of turn 0");
    expect(within(panel).getByText(/OPENGUIDE_CAPTURE_CONTENT=1/)).toBeInTheDocument();
    expect(within(panel).getByRole("table", { name: "Rule results for this turn" })).toBeInTheDocument();
  });
});

describe("what the sensors detected", () => {
  it("lists each rule with its reading, the minimum, the result and what it added to drift", async () => {
    show(api(withContent));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "ArrowRight" });                                   // turn 1: sign_off missed
    const table = within(screen.getByLabelText("Details of turn 1")).getByRole("table", { name: "Rule results for this turn" });
    const row = (id: string) => within(table).getByText(id).closest("tr")!;
    expect(row("sign_off")).toHaveTextContent("deterministic check");
    expect(row("sign_off")).toHaveTextContent("Missed");
    expect(row("sign_off")).toHaveTextContent("0.45");                                    // 0.5 x (0.9 - 0)
    expect(row("brevity")).toHaveTextContent("Met");
    expect(row("brevity")).toHaveTextContent("0.00");
    expect(within(table).getByText("Drift this turn").closest("tr")).toHaveTextContent("0.45");
  });

  it("explains the arithmetic when the columns add up, and says so when they cannot be broken down", async () => {
    show(api(withContent));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "ArrowRight" });
    expect(screen.getByLabelText("Details of turn 1")).toHaveTextContent("weight times how far it fell below its minimum");
  });

  it("with an unreadable contract it still shows readings and the shortfall, and does not invent weights", async () => {
    show(api(withContent, null));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "ArrowRight" });
    const panel = screen.getByLabelText("Details of turn 1");
    expect(within(panel).getByText("sign_off").closest("tr")).toHaveTextContent("short by 0.90");
    expect(panel).toHaveTextContent("weights couldn't be read");
  });
});

describe("what the contract did", () => {
  it("shows the response steps with the contract's own gates and which were reached", async () => {
    show(api(withContent));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "ArrowRight" });
    const steps = within(screen.getByLabelText("Details of turn 1")).getByRole("list", { name: "Response steps" });
    const items = within(steps).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("re-anchor at drift ≥ 0.1 — reached, and recorded for this turn");
    expect(items[0]).toHaveTextContent("Restate the contract's persona and boundaries");
    expect(items[1]).toHaveTextContent("escalate at drift ≥ 0.6 — not reached");
    expect(screen.getByLabelText("Details of turn 1")).toHaveTextContent("Action taken this turn: re-anchor");
  });

  it("says no action was taken on a clean turn", async () => {
    show(api(withContent));
    expect(await screen.findByLabelText("Details of turn 0")).toHaveTextContent("No action was taken this turn");
  });
});

describe("every turn", () => {
  it("lists each turn with what was said, whether the rules held, and what the contract did", async () => {
    show(api(withContent));
    const list = await screen.findByLabelText("Every turn");
    const rows = within(list).getAllByRole("row");
    expect(rows).toHaveLength(4);                                                         // header + 3 turns
    expect(rows[2]).toHaveTextContent("Can I use the app offline?");
    expect(rows[2]).toHaveTextContent("Missed: sign_off");
    expect(rows[2]).toHaveTextContent("re-anchor");
    expect(rows[1]).toHaveTextContent("All met");
    expect(rows[3]).toHaveTextContent("re-statement sent here");
  });

  it("picking a turn moves the replay to it", async () => {
    show(api(withContent));
    fireEvent.click(await screen.findByRole("button", { name: "Go to turn 1" }));
    expect(slider()).toHaveAttribute("aria-valuenow", "1");
    expect(screen.getByLabelText("Details of turn 1")).toBeInTheDocument();
  });

  it("without captured content the list still works and marks nothing as 'not recorded' columns", async () => {
    show(api(stateOnly));
    const list = await screen.findByLabelText("Every turn");
    expect(within(list).queryByText("User asked")).not.toBeInTheDocument();
    expect(within(list).getAllByRole("row")).toHaveLength(4);
  });
});

describe("what the contract requires", () => {
  it("lists the persona, the rules restated on drift, and what is measured", async () => {
    show(api(withContent));
    const panel = (await screen.findByText("What this contract requires")).closest("details")!;
    expect(panel).toHaveTextContent("concise plain-text support assistant");
    expect(panel).toHaveTextContent("end every reply with [END]");
    expect(within(panel).getByText("sign_off").closest("tr")).toHaveTextContent("deterministic check");
  });

  it("is simply absent when the contract can't be read", async () => {
    show(api(withContent, null));
    await screen.findByLabelText("Details of turn 0");
    expect(screen.queryByText("What this contract requires")).not.toBeInTheDocument();
  });
});

describe("activation steering on a turn", () => {
  const STEER = { ev: "STEER", turn: 2, gain: 0.05, band: [10, 19], pack_hash: "sha256:p" };
  const steered = [STATES[0]!, STATES[1]!, STATES[2]!, STEER] as Array<Record<string, unknown>>;

  it("says so on a steered turn: the gain, the layers, and why it was on", async () => {
    show(api(steered));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "End" });                                          // turn 2
    const note = within(screen.getByLabelText("Details of turn 2")).getByLabelText("Activation steering");
    expect(note).toHaveTextContent("Activation steering was on for this turn");
    expect(note).toHaveTextContent("gain 0.05");
    expect(note).toHaveTextContent("layers 10 to 18");
    expect(note).toHaveTextContent("because the previous turn needed a correction");
  });

  it("does not report the steering record as a record that was left out of the replay", async () => {
    show(api(steered));
    await screen.findByLabelText("Details of turn 0");
    expect(screen.queryByText(/not behavioral-state records/)).not.toBeInTheDocument();
  });

  it("says nothing about steering on a turn that wasn't steered", async () => {
    show(api(steered));
    expect(await screen.findByLabelText("Details of turn 0")).toBeInTheDocument();
    expect(screen.queryByLabelText("Activation steering")).not.toBeInTheDocument();
  });

  it("says nothing at all about steering for a run that never used it", async () => {
    show(api(stateOnly));
    await screen.findByLabelText("Details of turn 0");
    fireEvent.keyDown(slider(), { key: "End" });
    expect(screen.queryByLabelText("Activation steering")).not.toBeInTheDocument();
    expect(screen.queryByText(/steering/i)).not.toBeInTheDocument();
  });
});
