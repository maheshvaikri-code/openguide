import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { ApiError, type Api } from "../lib/api";
import type { Json, Pack, Run, TraceResponse } from "../lib/types";
import { ApiProvider } from "../ui/ApiContext";
import { ErrorBoundary } from "../ui/ErrorBoundary";
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
  manifest: { model: "mock:gpt-4o", seed: 7, simulated: true }, head: "sha256:head", verified: true,
  chain: { ok: true, checked: 4, break_at: null, reason: null }, cas_key: "k",
  records: [state(0, 0), state(1, 0.05), state(2, 0.4, "re_anchor"), state(3, 0.1)], ...over,
});
const contractBody = (threshold: number | undefined, halt?: string): { hash: string; contract: Json } => ({
  hash: "sha256:c0ffee",
  contract: { contract: { name: "coding-agent", version: "0.1.0" },
    recovery: threshold === undefined ? {} : { drift_threshold: threshold, actions: ["re_anchor", ...(halt ? [halt] : [])] } },
});
function fakeApi(over: Partial<Api> = {}): Api {
  return {
    health: async () => true,
    status: async () => ({ auth_required: true }),
    runs: async () => [run("a", { max_drift: 0.5 }), run("b"), run("c", { verified: false })],
    run: async (id) => run(id),
    trace: async () => trace(),
    contracts: async () => [{ hash: "sha256:c0ffee", name: "coding-agent", version: "0.1.0", enforcement_floor: "t3", invariants: 3 }],
    contract: async () => contractBody(0.05, "halt@0.60"),
    validate: async () => ({ ok: true, hash: "sha256:new", name: "x", version: "1", enforcement_floor: "t3", invariants: 1 }),
    register: async () => ({ contract_hash: "sha256:new" }),
    packs: async () => ({ packs: [], skipped: [] }),
    ...over,
  };
}
const wrap = (api: Api, ui: React.ReactElement) => render(<ApiProvider api={api}>{ui}</ApiProvider>);

beforeEach(() => { window.location.hash = ""; });
afterEach(() => vi.useRealTimers());

// ── B1: thresholds come from the run's own contract ────────────────────────
describe("contract thresholds are never invented", () => {
  it("replay draws the threshold the contract states (0.05), not a default", async () => {
    wrap(fakeApi(), <RunPage runId="r" />);
    expect(await screen.findByText("contract threshold 0.05")).toBeInTheDocument();
    expect(screen.queryByText(/0\.27/)).not.toBeInTheDocument();
    // turn 0 drift is 0 -> below; the panel says so using the contract's number
    expect(screen.getByLabelText("State at turn 0")).toHaveTextContent("Below this contract's threshold of 0.05; it halts the run at 0.6");
  });

  it("a different contract gets a different line", async () => {
    wrap(fakeApi({ contract: async () => contractBody(0.25, "halt@0.55") }), <RunPage runId="r" />);
    expect(await screen.findByText("contract threshold 0.25")).toBeInTheDocument();
  });

  it("an unreadable contract draws no threshold at all and says why", async () => {
    wrap(fakeApi({ contract: async () => { throw new ApiError(404, "no such contract"); } }), <RunPage runId="r" />);
    await screen.findByRole("slider", { name: "Replay position" });
    expect(screen.queryByText(/contract threshold/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("State at turn 0")).toHaveTextContent("threshold couldn't be read, so none is shown");
  });

  it("a contract with no recovery gate also draws none", async () => {
    wrap(fakeApi({ contract: async () => contractBody(undefined) }), <RunPage runId="r" />);
    await screen.findByRole("slider", { name: "Replay position" });
    expect(screen.queryByText(/contract threshold/)).not.toBeInTheDocument();
  });

  it("trajectory states the contract's threshold in words", async () => {
    wrap(fakeApi({ contract: async () => contractBody(0.05) }), <TrajectoryPage runId="r" />);
    const summary = await screen.findByLabelText("Summary of this path");
    expect(summary).toHaveTextContent("first reached the contract's threshold of 0.05 at turn 1");
    expect(summary).not.toHaveTextContent("0.27");
  });

  it("trajectory with an unreadable contract claims no threshold", async () => {
    wrap(fakeApi({ contract: async () => { throw new ApiError(500, "boom"); } }), <TrajectoryPage runId="r" />);
    expect(await screen.findByLabelText("Summary of this path")).toHaveTextContent("couldn't be read, so none is drawn");
  });

  it("the fleet legend no longer asserts a contract threshold", async () => {
    wrap(fakeApi(), <FleetPage />);
    await screen.findByLabelText("Fleet summary");
    expect(screen.queryByText("contract threshold")).not.toBeInTheDocument();
    expect(screen.getByText(/Each contract sets its own threshold/)).toBeInTheDocument();
  });
});

// ── M1: selection survives a reshuffling, polled list ──────────────────────
describe("fleet selection", () => {
  it("keeps the same run selected when a new, higher-drift run arrives at the top", async () => {
    vi.useFakeTimers();
    const runs = vi.fn()
      .mockResolvedValueOnce([run("a", { max_drift: 0.5 }), run("b", { max_drift: 0.4 })])
      .mockResolvedValue([run("z", { max_drift: 0.9 }), run("a", { max_drift: 0.5 }), run("b", { max_drift: 0.4 })]);
    wrap(fakeApi({ runs }), <FleetPage />);
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    const canvas = document.querySelector("canvas")!;
    fireEvent.focus(canvas);                                  // selects the first cell (a)
    fireEvent.keyDown(canvas, { key: "ArrowRight" });         // -> b
    expect(screen.getByLabelText("Selected run")).toHaveTextContent("b");

    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));   // poll: z is inserted at index 0
    const figures = screen.getByLabelText("Fleet summary");
    expect(within(figures).getByText("runs shown").previousElementSibling).toHaveTextContent("3");   // the new run is in the list
    const panel = screen.getByLabelText("Selected run");
    expect(within(panel).getByRole("heading", { level: 2 })).toHaveTextContent("b");   // still b, not whatever is at index 1
    expect(within(panel).getByRole("link", { name: "Replay this run" })).toHaveAttribute("href", "#/run/b");
  });

  it("clears the selection when the selected run leaves the list", async () => {
    vi.useFakeTimers();
    const runs = vi.fn()
      .mockResolvedValueOnce([run("a"), run("b")])
      .mockResolvedValue([run("a")]);
    wrap(fakeApi({ runs }), <FleetPage />);
    await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
    const canvas = document.querySelector("canvas")!;
    fireEvent.focus(canvas);
    fireEvent.keyDown(canvas, { key: "ArrowRight" });
    await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
    expect(within(screen.getByLabelText("Selected run")).getByRole("heading", { level: 2 })).toHaveTextContent("No run selected");
  });

  it("the model filter keeps offering the model you chose", async () => {
    const runs = vi.fn().mockImplementation(async () => [run("a", { model: "mock:claude" }), run("b", { model: "mock:gpt-4o" })]);
    wrap(fakeApi({ runs }), <FleetPage />);
    await screen.findByLabelText("Fleet summary");
    const select = screen.getByLabelText("Model") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "mock:claude" } });
    await waitFor(() => expect(select.value).toBe("mock:claude"));
    expect(within(select).getByRole("option", { name: "mock:claude" })).toBeInTheDocument();
  });
});

// ── M2 + minor 1: the register flow ────────────────────────────────────────
describe("contract registration", () => {
  it("shows the confirmation and keeps the editor after registering", async () => {
    const contracts = vi.fn().mockResolvedValue([{ hash: "sha256:c0ffee", name: "coding-agent", version: "0.1.0", enforcement_floor: "t3", invariants: 3 }]);
    const register = vi.fn().mockResolvedValue({ contract_hash: "sha256:newhash0000000000" });
    wrap(fakeApi({ contracts, register }), <ContractsPage selected="sha256:c0ffee" />);
    const editor = await screen.findByLabelText("Contract JSON");
    fireEvent.change(editor, { target: { value: JSON.stringify({ contract: { name: "edited", version: "1" } }) } });
    fireEvent.click(screen.getByRole("button", { name: "Check contract" }));
    await screen.findByText(/This would be a different contract/);
    fireEvent.click(screen.getByRole("button", { name: "Register as a new contract" }));

    expect(await screen.findByText(/Registered as/)).toBeInTheDocument();
    expect(register).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(contracts.mock.calls.length).toBeGreaterThan(1));       // list refreshed in the background
    expect(screen.getByText(/Registered as/)).toBeInTheDocument();                      // ...without wiping the notice
    expect((screen.getByLabelText("Contract JSON") as HTMLTextAreaElement).value).toContain("edited");   // ...or the edit
  });

  it("a register failure is shown", async () => {
    const register = vi.fn().mockRejectedValue(new ApiError(422, "contract is invalid"));
    wrap(fakeApi({ register }), <ContractsPage selected="sha256:c0ffee" />);
    await screen.findByLabelText("Contract JSON");
    fireEvent.click(screen.getByRole("button", { name: "Check contract" }));
    await screen.findByText(/This would be a different contract/);
    fireEvent.click(screen.getByRole("button", { name: "Register as a new contract" }));
    expect(await screen.findByText("contract is invalid")).toBeInTheDocument();
  });

  it("a slow check can't overwrite the result for text that has since changed", async () => {
    let finish!: (v: Awaited<ReturnType<Api["validate"]>>) => void;
    const validate = vi.fn().mockReturnValue(new Promise((res) => { finish = res; }));
    wrap(fakeApi({ validate }), <ContractsPage selected="sha256:c0ffee" />);
    const editor = await screen.findByLabelText("Contract JSON");
    fireEvent.click(screen.getByRole("button", { name: "Check contract" }));
    fireEvent.change(editor, { target: { value: '{"contract":{"name":"changed"}}' } });     // edit while it is in flight
    await act(async () => finish({ ok: true, hash: "sha256:stale", name: "x", version: "1", enforcement_floor: "t3", invariants: 1 }));
    expect(screen.queryByText(/This would be a different contract/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register as a new contract" })).toBeDisabled();
  });

  it("says so when the header can't be copied", async () => {
    Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) }, configurable: true });
    wrap(fakeApi(), <ContractsPage selected="sha256:c0ffee" />);
    fireEvent.click(await screen.findByRole("button", { name: "Copy header" }));
    expect(await screen.findByText(/Couldn't copy/)).toBeInTheDocument();
  });

  it("a contract with no name or version renders readable text, not 'null'", async () => {
    wrap(fakeApi({ contracts: async () => [{ hash: "sha256:x", name: null, version: null, enforcement_floor: "t3", invariants: 0 }] }), <ContractsPage selected={null} />);
    expect(await screen.findByText("Unnamed contract")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("null");
  });
});

// ── AC11: an error state for every page ────────────────────────────────────
describe("error states", () => {
  const boom = async () => { throw new ApiError(500, "The proxy had a problem."); };
  it("contracts", async () => {
    wrap(fakeApi({ contracts: boom }), <ContractsPage selected={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The proxy had a problem.");
  });
  it("packs", async () => {
    wrap(fakeApi({ packs: boom }), <PacksPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The proxy had a problem.");
  });
  it("audit report", async () => {
    wrap(fakeApi({ run: boom }), <AuditPage runId="x" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The proxy had a problem.");
  });
  it("audit search", async () => {
    wrap(fakeApi({ runs: boom }), <AuditPage runId={null} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The proxy had a problem.");
  });
  it("a failed comparison run is reported, and the main run still shows", async () => {
    const trace = vi.fn().mockImplementation(async (id: string) => {
      if (id === "other") throw new ApiError(500, "comparison trace is missing");
      return (await fakeApi().trace(id));
    });
    wrap(fakeApi({ trace, runs: async () => [run("r"), run("other")] }), <RunPage runId="r" />);
    const select = await screen.findByLabelText("Compare with");
    await screen.findByRole("option", { name: "other" });
    fireEvent.change(select, { target: { value: "other" } });
    expect(await screen.findByText(/Couldn't load the comparison run: comparison trace is missing/)).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Replay position" })).toBeInTheDocument();
  });
});

// ── M4: no false "verified" ────────────────────────────────────────────────
describe("runs with no stored trace", () => {
  const mixed = async () => [run("kept"), run("indexed", { trace_cas_key: "" }), run("broken", { verified: false })];
  it("fleet says 'Not re-checked' and counts them apart from broken chains", async () => {
    wrap(fakeApi({ runs: mixed }), <FleetPage />);
    const figures = await screen.findByLabelText("Fleet summary");
    expect(within(figures).getByText("with no stored trace to re-check").previousElementSibling).toHaveTextContent("1");
    expect(within(figures).getByText("with a broken trace chain").previousElementSibling).toHaveTextContent("1");
    expect(within(screen.getByLabelText("Most drifted runs")).getByText("Not re-checked")).toBeInTheDocument();
  });
  it("audit search says it too, and 'broken only' ignores them", async () => {
    wrap(fakeApi({ runs: mixed }), <AuditPage runId={null} />);
    const results = await screen.findByLabelText("Search results");
    expect(within(results).getByText("Not re-checked")).toBeInTheDocument();
    expect(results).toHaveTextContent("1 with no stored trace to re-check");
    fireEvent.click(screen.getByLabelText("Only runs with a broken chain"));
    expect(within(results).getAllByRole("row")).toHaveLength(2);                           // header + the one truly broken
  });
  it("a manifest without a simulated flag is 'not recorded', not 'No'", async () => {
    wrap(fakeApi({ trace: async () => trace({ manifest: { model: "m" } }) }), <AuditPage runId="r" />);
    await screen.findByText(/Hash chain consistent/);
    expect(screen.getByText("Simulated").nextElementSibling).toHaveTextContent("Not recorded");
  });
});

// ── M5 + auth notice ───────────────────────────────────────────────────────
describe("app chrome", () => {
  it("badges a fully simulated fleet, an included-simulated one, and a real one differently", async () => {
    const { unmount } = render(<App api={fakeApi({ runs: async () => [run("a"), run("b")] })} />);
    expect(await screen.findByText("Simulated data")).toBeInTheDocument();
    unmount();
    const mixed = render(<App api={fakeApi({ runs: async () => [run("a"), run("b", { model: "openai:gpt-4o" })] })} />);
    expect(await screen.findByText("Includes simulated runs")).toBeInTheDocument();
    mixed.unmount();
    render(<App api={fakeApi({ runs: async () => [run("a", { model: "openai:gpt-4o" })] })} />);
    await screen.findByLabelText("Console sections");
    await waitFor(() => expect(screen.queryByText(/simulated/i)).not.toBeInTheDocument());
  });

  it("warns when the proxy has no admin token, and not when it has one", async () => {
    const open = render(<App api={fakeApi({ status: async () => ({ auth_required: false }) })} />);
    expect(await screen.findByText(/no admin token set/)).toBeInTheDocument();
    open.unmount();
    render(<App api={fakeApi()} />);
    await screen.findByLabelText("Console sections");
    expect(screen.queryByText(/no admin token set/)).not.toBeInTheDocument();
  });

  it("offers a skip link to the main content", async () => {
    render(<App api={fakeApi()} />);
    expect(await screen.findByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("renders the error boundary instead of a blank page when a view throws", () => {
    const Bomb = () => { throw new Error("kaboom"); };
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary><Bomb /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toHaveTextContent("This view hit an unexpected problem");
    expect(screen.getByRole("alert")).toHaveTextContent("kaboom");
  });
});

// ── M7/M8: pack counts and malformed cards ─────────────────────────────────
describe("packs", () => {
  const pack = (over: Partial<Pack> = {}): Pack => ({
    name: "q", model_id: "qwen2.5-7b", pack_hash: "sha256:abc", signals: ["anchor"], layers: 32, dim: 64, status: "synthetic",
    evals: { mmlu_delta_at_gain: { "0.2": null }, gsm8k_delta_at_gain: { "0.2": null }, coherence_ok: null }, ...over,
  });
  it("does not count simulated runs against the real model's pack", async () => {
    const runs = async () => [run("a", { model: "mock:qwen2.5-7b" }), run("b", { model: "mock:qwen2.5-7b" })];
    wrap(fakeApi({ runs, packs: async () => ({ packs: [pack()], skipped: [] }) }), <PacksPage />);
    expect(await screen.findByText("No runs recorded on this model")).toBeInTheDocument();
  });
  it("counts runs on exactly that model", async () => {
    const runs = async () => [run("a", { model: "qwen2.5-7b" }), run("b", { model: "qwen2.5-7b" }), run("c", { model: "other" })];
    wrap(fakeApi({ runs, packs: async () => ({ packs: [pack()], skipped: [] }) }), <PacksPage />);
    expect(await screen.findByText("2 runs recorded on this model")).toBeInTheDocument();
  });
  it("says the count is unavailable instead of claiming zero when runs can't be loaded", async () => {
    const runs = async () => { throw new ApiError(500, "down"); };
    wrap(fakeApi({ runs, packs: async () => ({ packs: [pack()], skipped: [] }) }), <PacksPage />);
    expect(await screen.findByText("Run count unavailable")).toBeInTheDocument();
  });
  it("a card missing fields renders instead of crashing", async () => {
    const odd = { name: "odd", model_id: "m", pack_hash: "sha256:x", layers: 1, dim: 1, status: "derived" } as unknown as Pack;
    wrap(fakeApi({ packs: async () => ({ packs: [odd], skipped: [] }) }), <PacksPage />);
    expect(await screen.findByLabelText("Pack for m")).toBeInTheDocument();
  });
});

// ── accessibility: event rows ──────────────────────────────────────────────
describe("replay events", () => {
  it("each event row has a real button that jumps to its turn", async () => {
    wrap(fakeApi(), <RunPage runId="r" />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to turn 2" }));
    expect(screen.getByRole("slider", { name: "Replay position" })).toHaveAttribute("aria-valuenow", "2");
  });
});
