import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Api } from "../lib/api";
import type { Json, Run } from "../lib/types";
import { ApiProvider } from "../ui/ApiContext";
import { RunExplainer } from "../ui/RunExplainer";
import { FleetPage } from "./Fleet";

const run = (id: string, over: Partial<Run> = {}): Run => ({
  run_id: id, contract_hash: "sha256:c", model: "local:qwen", tier: "t2", turns: 5, max_drift: 0.1, recoveries: 0,
  halted: false, verified: true, trace_hash: "sha256:t", trace_cas_key: "k", created: "", ...over,
});

const CONTRACT: Json = {
  contract: { name: "support-plain-brief", version: "1" },
  invariants: [{ id: "sign_off", measure: "structural:sign_off", floor: 0.9, weight: 0.5 }],
  recovery: { drift_threshold: 0.1, actions: ["re_anchor"] },
};

const inv = (r: number | null) => ({ sign_off: { reading: r, floor: 0.9, violated: r !== null && r < 0.9 } });
const state = (turn: number, drift: number, r: number | null, fired: string | null = null) => ({
  ev: "STATE", turn, tier_active: "t2", drift, invariants: inv(r), signals_active: {}, recovery_fired: fired,
  validation_failures: [], sensor_gaps: r === null ? ["sign_off"] : [], reanchored: Boolean(fired),
});
// turn 0 fine; 1-2 missed with a correction at 1; 3 and 4 back to fine
const RECORDS = [state(0, 0, 1), state(1, 0.45, 0, "re_anchor"), state(2, 0.45, 0), state(3, 0, 1), state(4, 0, 1)];

function api(runs: Run[], opts: { contract?: Json | null; records?: Array<Record<string, unknown>>; traceError?: boolean; trace?: ReturnType<typeof vi.fn> } = {}): Api {
  const contract = opts.contract === undefined ? CONTRACT : opts.contract;
  return {
    health: async () => true, status: async () => ({ auth_required: true }), runs: async () => runs,
    run: async (id: string) => runs.find((r) => r.run_id === id)!,
    trace: opts.trace ?? (async () => {
      if (opts.traceError) throw new Error("trace store is down");
      return { manifest: {}, head: "h", verified: true, cas_key: "k", records: opts.records ?? RECORDS } as never;
    }),
    contracts: async () => [{ hash: "sha256:c", name: "support-plain-brief", version: "0.1.0", enforcement_floor: "t2", invariants: 1 }],
    contract: async (hash: string) => { if (contract === null) throw new Error("gone"); return { hash, contract }; },
    validate: async () => ({ ok: false, error: "x" }), register: async () => ({ contract_hash: "x" }),
    packs: async () => ({ packs: [], skipped: [] }),
  } as Api;
}
const show = (a: Api) => render(<ApiProvider api={a}><FleetPage /></ApiProvider>);

const ARMS = [
  run("arm-a-s0", { max_drift: 0.05 }), run("arm-a-s1", { max_drift: 0.1 }), run("arm-a-s2", { max_drift: 0.15, recoveries: 1 }),
  run("arm-b-s0", { max_drift: 0.45, recoveries: 3 }), run("arm-b-s1", { max_drift: 0.9, recoveries: 2, halted: true }),
  run("arm-b-s2", { max_drift: 0.5, recoveries: 1, verified: false }),
];

/** Select a run the way a keyboard user does: focus the field (selects the first run) and press Enter-free arrows. */
async function pickFirst() {
  await screen.findByLabelText("Fleet summary");
  const canvas = document.querySelector("canvas")!;
  fireEvent.focus(canvas);
  return screen.getByLabelText("Selected run");
}
beforeEach(() => { window.location.hash = ""; });

describe("the restored layout", () => {
  it("is the grid with its legend, the panel on the right and the most-drifted table, with no big guide", async () => {
    show(api(ARMS));
    await screen.findByLabelText("Fleet summary");
    expect(document.querySelector("canvas")).not.toBeNull();
    expect(screen.getByLabelText("Legend")).toHaveTextContent("Each contract sets its own threshold");
    expect(screen.getByLabelText("Legend")).toHaveTextContent("Dot: flagged halted. Red frame: trace chain broken. Cyan frame: arrived while you watched.");
    expect(screen.getByLabelText("Selected run")).toBeInTheDocument();
    expect(screen.getByLabelText("Most drifted runs")).toBeInTheDocument();
    expect(screen.queryByText("How to read this page")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Series /)).not.toBeInTheDocument();            // grouping is opt-in
  });

  it("before anything is selected, the panel says what clicking does", async () => {
    show(api(ARMS));
    await screen.findByLabelText("Fleet summary");
    expect(screen.getByLabelText("Selected run")).toHaveTextContent("click it to see why it has that colour and what was detected in it");
  });
});

describe("the optional series view", () => {
  it("is offered when runs form several series, and switches to groups with a summary each and back", async () => {
    show(api(ARMS));
    await screen.findByLabelText("Fleet summary");
    fireEvent.click(screen.getByRole("radio", { name: "By series" }));
    const b = screen.getByLabelText("Series arm-b");
    expect(b).toHaveTextContent("Average peak drift 0.62");
    expect(b).toHaveTextContent(/1 of 3.*halted/);
    expect(within(b).getAllByRole("button")).toHaveLength(3);
    fireEvent.click(screen.getByRole("radio", { name: "All runs" }));
    expect(screen.queryByLabelText("Series arm-a")).not.toBeInTheDocument();
    expect(document.querySelector("canvas")).not.toBeNull();
  });

  it("offers no layout choice when the runs don't form several series", async () => {
    show(api([run("run-000001"), run("run-000002"), run("run-000003")]));
    await screen.findByLabelText("Fleet summary");
    expect(screen.queryByRole("radio", { name: "By series" })).not.toBeInTheDocument();
  });

  it("selecting a square in the series view opens the same explanation", async () => {
    show(api(ARMS));
    await screen.findByLabelText("Fleet summary");
    fireEvent.click(screen.getByRole("radio", { name: "By series" }));
    fireEvent.click(within(screen.getByLabelText("Series arm-b")).getByRole("button", { name: /^arm-b-s0/ }));
    const panel = screen.getByLabelText("Selected run");
    expect(within(panel).getByRole("heading", { level: 2 })).toHaveTextContent("arm-b-s0");
    expect(await within(panel).findByText("Why this colour")).toBeInTheDocument();
    expect(panel).toHaveTextContent("One of 3 runs named arm-b…");
  });
});

describe("what opens when you click a square", () => {
  it("explains the colour: what drift is, this run's peak, and this contract's own gate", async () => {
    show(api([run("a", { max_drift: 0.45, recoveries: 1 }), run("b")]));
    const panel = await pickFirst();
    expect(await within(panel).findByText("Why this colour")).toBeInTheDocument();
    expect(panel).toHaveTextContent("The colour is the highest drift this run reached, 0.45.");
    expect(panel).toHaveTextContent("0 means every rule held.");
    expect(await within(panel).findByText(/This contract starts responding at drift 0.1, so this run crossed it/)).toBeInTheDocument();
  });

  it("says a run never reached the gate when it didn't", async () => {
    show(api([run("a", { max_drift: 0.05 })]));
    const panel = await pickFirst();
    expect(await within(panel).findByText(/this run never reached it/)).toBeInTheDocument();
  });

  it("explains only the marks that are actually on this square", async () => {
    show(api([run("a", { max_drift: 0.9, halted: true, verified: false })]));
    const marks = within(await pickFirst()).getByRole("list", { name: "Marks on this square" });
    expect(marks).toHaveTextContent("A dark dot: the run is flagged halted in the record");
    expect(marks).toHaveTextContent("does not itself block later requests");
    expect(marks).toHaveTextContent("A red frame: this run's trace no longer verifies");
    expect(marks).not.toHaveTextContent("cyan frame");
  });

  it("shows no marks list for a run with no marks", async () => {
    show(api([run("a")]));
    const panel = await pickFirst();
    await within(panel).findByText("Why this colour");
    expect(within(panel).queryByRole("list", { name: "Marks on this square" })).not.toBeInTheDocument();
  });

  it("a freshly arrived run is explained as arrived while you were watching", () => {
    render(<ApiProvider api={api([run("a")])}><RunExplainer run={run("a")} isNew series={undefined} filtered={false} contractName="c" /></ApiProvider>);
    expect(screen.getByRole("list", { name: "Marks on this square" })).toHaveTextContent("A cyan frame: this run arrived while you were watching.");
  });

  it("says what was detected, read from the run's own trace", async () => {
    show(api([run("a", { max_drift: 0.45, recoveries: 1 })]));
    const panel = await pickFirst();
    expect(await within(panel).findByText("Drift was at or above 0.1 on 2 of 5 turns.")).toBeInTheDocument();
    expect(panel).toHaveTextContent("The first correction fired at turn 1.");
    expect(panel).toHaveTextContent("Drift was back below 0.1 at turn 3, 2 turns after the first correction.");
    const row = within(within(panel).getByRole("table", { name: "Rules across this run" })).getByText("sign_off").closest("tr")!;
    expect(row).toHaveTextContent("deterministic check");
    expect(row).toHaveTextContent("2 of 5 turns");
    expect(row).toHaveTextContent("0.00");                                      // the lowest reading it reached
  });

  it("says when drift never came back down", async () => {
    show(api([run("a")], { records: [state(0, 0.45, 0, "re_anchor"), state(1, 0.45, 0)] }));
    expect(await within(await pickFirst()).findByText("Drift did not come back below 0.1 before the run ended.")).toBeInTheDocument();
  });

  it("says no correction fired for a clean run, and shows every rule as never missed", async () => {
    show(api([run("a")], { records: [state(0, 0, 1), state(1, 0, 1)] }));
    const panel = await pickFirst();
    expect(await within(panel).findByText("No correction fired.")).toBeInTheDocument();
    expect(within(panel).getByRole("table", { name: "Rules across this run" })).toHaveTextContent("never (2 turns)");
  });

  it("notes turns with no reading", async () => {
    show(api([run("a")], { records: [state(0, 0, 1), state(1, 0, null)] }));
    expect(await within(await pickFirst()).findByText("No reading was produced on 1 turn.")).toBeInTheDocument();
  });

  it("explains a run with no stored trace without asking for one", async () => {
    const trace = vi.fn();
    show(api([run("a", { trace_cas_key: "" })], { trace }));
    const panel = await pickFirst();
    expect(await within(panel).findByText(/in the fleet index only/)).toBeInTheDocument();
    expect(trace).not.toHaveBeenCalled();
  });

  it("reports a trace that can't be loaded, and the rest of the explanation still shows", async () => {
    show(api([run("a", { max_drift: 0.45 })], { traceError: true }));
    const panel = await pickFirst();
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Couldn't load this run's trace: trace store is down");
    expect(panel).toHaveTextContent("The colour is the highest drift this run reached");
  });

  it("makes no gate claims when the contract can't be read, but still describes the run's own trace", async () => {
    show(api([run("a", { max_drift: 0.45 })], { contract: null }));
    const panel = await pickFirst();
    expect(await within(panel).findByText(/This contract's gate couldn't be read, so none is used here/)).toBeInTheDocument();
    expect(panel).not.toHaveTextContent("starts responding");
    expect(panel).toHaveTextContent("The first correction fired at turn 1.");
  });

  it("each part opens and closes on its own, with the run details tucked away by default", async () => {
    show(api([run("a")]));
    const panel = await pickFirst();
    await within(panel).findByText("Why this colour");
    const sections = panel.querySelectorAll("details.explain");
    expect([...sections].map((d) => d.hasAttribute("open"))).toEqual([true, true, false]);
    expect(within(panel).getByText("Run details")).toBeInTheDocument();
  });

  it("the details include the contract, the model and the corrections, and link to the replay and audit", async () => {
    show(api([run("a", { recoveries: 2 })]));
    const panel = await pickFirst();
    await within(panel).findByText("Run details");
    expect(panel).toHaveTextContent("Corrections2");
    expect(panel).toHaveTextContent("support-plain-brief");
    expect(within(panel).getByRole("link", { name: "Replay this run" })).toHaveAttribute("href", "#/run/a");
    expect(within(panel).getByRole("link", { name: "Audit" })).toHaveAttribute("href", "#/audit/a");
  });

  it("switching to another square replaces the explanation", async () => {
    show(api([run("a", { max_drift: 0.45 }), run("b", { max_drift: 0.05 })]));
    const panel = await pickFirst();
    await waitFor(() => expect(panel).toHaveTextContent("highest drift this run reached, 0.45"));
    fireEvent.keyDown(document.querySelector("canvas")!, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByLabelText("Selected run")).toHaveTextContent("highest drift this run reached, 0.05"));
    expect(screen.getByLabelText("Selected run")).not.toHaveTextContent("0.45");
  });
});


describe("steering in the selected run's details", () => {
  const steer = (turn: number) => ({ ev: "STEER", turn, gain: 0.05, band: [10, 19], pack_hash: "sha256:p" });

  it("says how many turns were steered, once the trace is read", async () => {
    show(api([run("a")], { records: [...RECORDS, steer(1), steer(4)] }));
    const panel = await pickFirst();
    await within(panel).findByText("What was detected in this run");
    await waitFor(() => expect(panel).toHaveTextContent("SteeringT0 on 2 turns"));
  });

  it("has no steering row for a run that wasn't steered", async () => {
    show(api([run("a")]));
    const panel = await pickFirst();
    await within(panel).findByText("Drift was at or above 0.1 on 2 of 5 turns.");
    expect(panel).not.toHaveTextContent("Steering");
  });
});
