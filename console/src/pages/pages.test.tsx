import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Api } from "../lib/api";
import type { Pack, Run, StateRecord, TraceResponse } from "../lib/types";
import { ApiProvider } from "../ui/ApiContext";
import { AuditPage } from "./Audit";
import { ContractsPage } from "./Contracts";
import { FleetPage } from "./Fleet";
import { PacksPage } from "./Packs";
import { RunPage } from "./Run";
import TrajectoryPage from "./Trajectory";

vi.mock("../ui/Scene3D", () => ({ Scene3D: () => <div data-testid="scene" /> }));

const run = (id: string, over: Partial<Run> = {}): Run => ({
  run_id: id, contract_hash: "sha256:c0ffee", model: "mock:gpt-4o", tier: "t2", turns: 4, max_drift: 0.1,
  recoveries: 0, halted: false, verified: true, trace_hash: "sha256:t", trace_cas_key: "k", created: "2026-11-06", ...over,
});

const state = (turn: number, drift: number, fired: string | null = null): Record<string, unknown> => ({
  ev: "STATE", turn, tier_active: "t2", drift,
  invariants: { adherence: { reading: 0.9 - drift, floor: 0.85, violated: drift > 0.05 } },
  signals_active: { anchor: 0.3 }, recovery_fired: fired, validation_failures: [], sensor_gaps: [], reanchored: Boolean(fired),
});

const trace = (over: Partial<TraceResponse> = {}): TraceResponse => ({
  manifest: { model: "mock:gpt-4o", seed: 7, runtime: "t", simulated: true }, head: "sha256:head", verified: true,
  chain: { ok: true, checked: 4, break_at: null, reason: null }, cas_key: "k",
  records: [state(0, 0), state(1, 0.05), state(2, 0.4, "re_anchor"), state(3, 0.1)], ...over,
});

function fakeApi(over: Partial<Api> = {}): Api {
  return {
    health: async () => true,
    runs: async () => [run("a", { max_drift: 0.5, halted: true }), run("b"), run("c", { verified: false })],
    run: async (id) => run(id),
    trace: async () => trace(),
    contracts: async () => [{ hash: "sha256:c0ffee", name: "coding-agent", version: "0.1.0", enforcement_floor: "t3", invariants: 3 }],
    contract: async (hash) => ({ hash, contract: { contract: { name: "coding-agent", version: "0.1.0" }, recovery: { drift_threshold: 0.27 } } }),
    validate: async () => ({ ok: true, hash: "sha256:new", name: "x", version: "1", enforcement_floor: "t3", invariants: 1 }),
    register: async () => ({ contract_hash: "sha256:new" }),
    packs: async () => ({ packs: [], skipped: [] }),
    status: async () => ({ auth_required: true }),
    ...over,
  };
}
const wrap = (api: Api, ui: React.ReactElement) => render(<ApiProvider api={api}>{ui}</ApiProvider>);

beforeEach(() => {
  window.location.hash = "";
  vi.restoreAllMocks();
});

// ── Fleet (AC5, AC11) ──────────────────────────────────────────────────────
describe("Fleet", () => {
  it("loading -> success with summary figures and the worst-runs table", async () => {
    wrap(fakeApi(), <FleetPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    const figures = await screen.findByLabelText("Fleet summary");
    expect(within(figures).getByText("runs shown").previousElementSibling).toHaveTextContent("3");
    const table = within(screen.getByLabelText("Most drifted runs")).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4); // header + 3 runs
    expect(within(table).getByText("Chain broken")).toBeInTheDocument(); // status is text, not colour
  });

  it("empty: no runs at all explains how to get some", async () => {
    wrap(fakeApi({ runs: async () => [] }), <FleetPage />);
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.getByText(/make console-demo/)).toBeInTheDocument();
  });

  it("error: shows what happened and offers a retry", async () => {
    const runs = vi.fn().mockRejectedValueOnce(new ApiError(0, "Couldn't reach the proxy.")).mockResolvedValue([run("a")]);
    wrap(fakeApi({ runs }), <FleetPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach the proxy.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Fleet summary")).toBeInTheDocument();
  });

  it("401: asks for the admin token instead of failing", async () => {
    wrap(fakeApi({ runs: async () => { throw new ApiError(401, "This proxy needs an admin token."); } }), <FleetPage />);
    expect(await screen.findByLabelText("Admin token")).toBeInTheDocument();
  });

  it("filters that match nothing offer to clear them", async () => {
    const runs = vi.fn().mockResolvedValueOnce([run("a")]).mockResolvedValue([]);
    wrap(fakeApi({ runs }), <FleetPage />);
    await screen.findByLabelText("Fleet summary");
    fireEvent.click(screen.getByLabelText("Halted runs only"));
    expect(await screen.findByText("No runs match these filters")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("passes the min-drift filter to the API", async () => {
    const runs = vi.fn().mockResolvedValue([run("a")]);
    wrap(fakeApi({ runs }), <FleetPage />);
    await screen.findByLabelText("Fleet summary");
    fireEvent.change(screen.getByLabelText(/Minimum peak drift/), { target: { value: "0.3" } });
    await waitFor(() => expect(runs).toHaveBeenLastCalledWith(expect.objectContaining({ min_drift: 0.3 })));
  });
});

// ── Run (AC6) ──────────────────────────────────────────────────────────────
describe("Run", () => {
  it("jump to first correction lands on the turn where it fired", async () => {
    wrap(fakeApi(), <RunPage runId="demo-governed" />);
    const jump = await screen.findByRole("button", { name: /Jump to first correction \(turn 2\)/ });
    fireEvent.click(jump);
    expect(screen.getByRole("slider", { name: "Replay position" })).toHaveAttribute("aria-valuenow", "2");
    expect(screen.getByLabelText("State at turn 2")).toHaveTextContent("re-anchor");
  });

  it("keyboard moves the playhead one turn at a time", async () => {
    wrap(fakeApi(), <RunPage runId="r" />);
    const slider = await screen.findByRole("slider", { name: "Replay position" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(slider).toHaveAttribute("aria-valuenow", "2");
    fireEvent.keyDown(slider, { key: "End" });
    expect(slider).toHaveAttribute("aria-valuenow", "3");
  });

  it("empty: a trace without behavioral-state records says so", async () => {
    wrap(fakeApi({ trace: async () => trace({ records: [{ ev: "TOOL_POLICY" }] }) }), <RunPage runId="r" />);
    expect(await screen.findByText("This run has no recorded turns")).toBeInTheDocument();
  });

  it("a run that exists only in the fleet index explains itself instead of erroring", async () => {
    const traceFn = vi.fn();
    wrap(fakeApi({ run: async (id) => run(id, { trace_cas_key: "" }), trace: traceFn }), <RunPage runId="idx-only" />);
    expect(await screen.findByText("This run has no stored trace")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(traceFn).not.toHaveBeenCalled(); // don't ask the server for a trace we know isn't there
    expect(screen.getByRole("link", { name: "Choose a run with a trace" })).toBeInTheDocument();
  });

  it("error: unknown run is reported, not blank", async () => {
    wrap(fakeApi({ run: async () => { throw new ApiError(404, "no such run"); } }), <RunPage runId="nope" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no such run");
  });

  it("no run chosen: asks the server for runs with a stored trace, so the limit can't hide them", async () => {
    const runs = vi.fn().mockResolvedValue([run("with", {})]);
    wrap(fakeApi({ runs }), <RunPage runId={null} />);
    expect(await screen.findByRole("link", { name: "with" })).toBeInTheDocument();
    expect(runs).toHaveBeenCalledWith(expect.objectContaining({ has_trace: true }));
  });
});

// ── Trajectory (AC7) ───────────────────────────────────────────────────────
describe("Trajectory", () => {
  it("summarises the path in words, not only in 3D", async () => {
    wrap(fakeApi(), <TrajectoryPage runId="r" />);
    expect(await screen.findByTestId("scene")).toBeInTheDocument();
    expect(screen.getByLabelText("Summary of this path")).toHaveTextContent("first reached the contract's threshold of 0.27 at turn 2");
    expect(screen.getByLabelText("Summary of this path")).toHaveTextContent("first correction fired at turn 2");
  });

  it("empty: a trace with no turns says so", async () => {
    wrap(fakeApi({ trace: async () => trace({ records: [] }) }), <TrajectoryPage runId="r" />);
    expect(await screen.findByText("No turns to plot")).toBeInTheDocument();
  });

  it("a fleet-index-only run explains itself and never requests a trace", async () => {
    const traceFn = vi.fn();
    wrap(fakeApi({ run: async (id) => run(id, { trace_cas_key: "" }), trace: traceFn }), <TrajectoryPage runId="idx" />);
    expect(await screen.findByText("This run has no stored trace")).toBeInTheDocument();
    expect(traceFn).not.toHaveBeenCalled();
  });

  it("error state renders when the run can't be loaded", async () => {
    wrap(fakeApi({ run: async () => { throw new ApiError(404, "no such run"); } }), <TrajectoryPage runId="x" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no such run");
  });
});

// ── Contracts (AC8) ────────────────────────────────────────────────────────
describe("Contracts", () => {
  it("invalid JSON shows the problem beside the editor and blocks the check", async () => {
    wrap(fakeApi(), <ContractsPage selected="sha256:c0ffee" />);
    const editor = await screen.findByLabelText("Contract JSON");
    fireEvent.change(editor, { target: { value: "{ not json" } });
    expect(await screen.findByText(/isn't valid JSON yet/)).toBeInTheDocument();
    expect(editor).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Check contract" })).toBeDisabled();
  });

  it("a server rejection is shown and nothing is registered", async () => {
    const register = vi.fn();
    wrap(fakeApi({ validate: async () => ({ ok: false, error: "enforcement_floor must be one of ['t0']" }), register }), <ContractsPage selected="sha256:c0ffee" />);
    await screen.findByLabelText("Contract JSON");
    fireEvent.click(screen.getByRole("button", { name: "Check contract" }));
    expect(await screen.findByText(/The proxy rejected this contract: enforcement_floor/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register as a new contract" })).toBeDisabled();
    expect(register).not.toHaveBeenCalled();
  });

  it("a valid edit shows the new hash and enables registering", async () => {
    wrap(fakeApi(), <ContractsPage selected="sha256:c0ffee" />);
    await screen.findByLabelText("Contract JSON");
    fireEvent.click(screen.getByRole("button", { name: "Check contract" }));
    expect(await screen.findByText(/This would be a different contract/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register as a new contract" })).toBeEnabled();
  });

  it("shows the activation header", async () => {
    wrap(fakeApi(), <ContractsPage selected="sha256:c0ffee" />);
    expect(await screen.findByText("X-OpenGuide-Contract: sha256:c0ffee")).toBeInTheDocument();
  });

  it("empty: no contracts explains how to add one", async () => {
    wrap(fakeApi({ contracts: async () => [] }), <ContractsPage selected={null} />);
    expect(await screen.findByText("No contracts registered")).toBeInTheDocument();
  });
});

// ── Packs (AC9) ────────────────────────────────────────────────────────────
describe("Packs", () => {
  const pack = (over: Partial<Pack> = {}): Pack => ({
    name: "q", model_id: "qwen2.5-7b", pack_hash: "sha256:abc", signals: ["anchor"], layers: 32, dim: 64, status: "synthetic",
    evals: { mmlu_delta_at_gain: { "0.2": null, "0.4": -0.8 }, gsm8k_delta_at_gain: { "0.2": null, "0.4": null }, coherence_ok: null }, ...over,
  });

  it("an unmeasured eval reads 'not measured', never zero", async () => {
    wrap(fakeApi({ packs: async () => ({ packs: [pack()], skipped: [] }) }), <PacksPage />);
    const region = await screen.findByLabelText("Pack for qwen2.5-7b");
    expect(within(region).getAllByText(/not measured/).length).toBeGreaterThanOrEqual(4);
    expect(region).toHaveTextContent("-0.80 pts");
    expect(region).not.toHaveTextContent("0.00");
    expect(region).toHaveTextContent("not derived from activations");
  });

  it("partial: skipped packs are reported while the rest still render", async () => {
    wrap(fakeApi({ packs: async () => ({ packs: [pack()], skipped: ["bad"] }) }), <PacksPage />);
    expect(await screen.findByText(/1 pack was skipped/)).toBeInTheDocument();
    expect(screen.getByLabelText("Pack for qwen2.5-7b")).toBeInTheDocument();
  });

  it("empty explains how to build a pack", async () => {
    wrap(fakeApi(), <PacksPage />);
    expect(await screen.findByText("No packs found")).toBeInTheDocument();
  });
});

// ── Audit (AC10) ───────────────────────────────────────────────────────────
describe("Audit", () => {
  it("a verified trace is reported as intact", async () => {
    wrap(fakeApi(), <AuditPage runId="ok" />);
    expect(await screen.findByText("Hash chain consistent: no record changed after it was written")).toBeInTheDocument();
    expect(screen.getByText(/does not prove who wrote it/)).toBeInTheDocument();
  });

  it("a broken chain says where it breaks, accuses no specific record, and keeps the caveat beside it", async () => {
    const bad = trace({
      verified: false,
      chain: { ok: false, checked: 2, break_at: 2, reason: "the chain breaks between record 1 and record 2: one of them was altered, or records between them were removed or reordered" },
    });
    wrap(fakeApi({ trace: async () => bad, run: async (id) => run(id, { verified: false }) }), <AuditPage runId="bad" />);
    expect(await screen.findByText("Hash chain broken: this record no longer matches itself")).toBeInTheDocument();
    expect(screen.getByText(/The chain breaks between record 1 and record 2: one of them was altered, or records between them were removed or reordered\. The first 2 records link correctly\./)).toBeInTheDocument();
    expect(screen.queryByText(/currently reads drift/)).not.toBeInTheDocument();           // no accusation of one record
    expect(screen.getByText(/does not prove who wrote it/)).toBeInTheDocument();           // caveat sits with the verdict
    const records = screen.getByText("Records").nextElementSibling;
    expect(records).toHaveTextContent("4");                                                // trace length, not how far it verified
  });

  it("a run without a stored trace is explained, not faked", async () => {
    wrap(fakeApi({ run: async (id) => run(id, { trace_cas_key: "" }) }), <AuditPage runId="x" />);
    expect(await screen.findByText("No stored trace for this run")).toBeInTheDocument();
  });

  it("search can narrow to broken chains", async () => {
    wrap(fakeApi(), <AuditPage runId={null} />);
    await screen.findByLabelText("Search results");
    fireEvent.click(screen.getByLabelText("Only runs with a broken chain"));
    const rows = within(screen.getByLabelText("Search results")).getAllByRole("row");
    expect(rows).toHaveLength(2); // header + run c
    expect(within(rows[1]!).getByRole("link", { name: "c" })).toBeInTheDocument();
  });

  it("search with no match says so", async () => {
    wrap(fakeApi(), <AuditPage runId={null} />);
    await screen.findByLabelText("Search results");
    fireEvent.change(screen.getByLabelText("Run id or contract hash"), { target: { value: "zzz" } });
    expect(await screen.findByText(/No run matches that search/)).toBeInTheDocument();
  });
});

export type { StateRecord };
