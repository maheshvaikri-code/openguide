import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { Api } from "../lib/api";
import type { Json, Run } from "../lib/types";
import { ApiProvider } from "../ui/ApiContext";
import { FleetPage } from "./Fleet";

const run = (id: string, over: Partial<Run> = {}): Run => ({
  run_id: id, contract_hash: "sha256:c", model: "local:qwen", tier: "t2", turns: 16, max_drift: 0.1, recoveries: 0,
  halted: false, verified: true, trace_hash: "sha256:t", trace_cas_key: "k", created: "", ...over,
});

const CONTRACT: Json = { contract: { name: "c", version: "1" }, recovery: { drift_threshold: 0.1, actions: ["re_anchor"] } };

function api(runs: Run[], contract: Json | null = CONTRACT): Api {
  return {
    health: async () => true, status: async () => ({ auth_required: true }), runs: async () => runs,
    run: async (id: string) => runs.find((r) => r.run_id === id)!, trace: async () => ({} as never),
    contracts: async () => [{ hash: "sha256:c", name: "support-plain-brief", version: "0.1.0", enforcement_floor: "t2", invariants: 3 }],
    contract: async (hash: string) => { if (contract === null) throw new Error("gone"); return { hash, contract }; },
    validate: async () => ({ ok: false, error: "x" }), register: async () => ({ contract_hash: "x" }),
    packs: async () => ({ packs: [], skipped: [] }),
  } as Api;
}
const show = (a: Api) => render(<ApiProvider api={a}><FleetPage /></ApiProvider>);

// two experiment arms of three runs each; arm-b drifts more
const ARMS = [
  run("arm-a-s0", { max_drift: 0.05 }), run("arm-a-s1", { max_drift: 0.1 }), run("arm-a-s2", { max_drift: 0.15, recoveries: 1 }),
  run("arm-b-s0", { max_drift: 0.45, recoveries: 3 }), run("arm-b-s1", { max_drift: 0.9, recoveries: 2, halted: true }),
  run("arm-b-s2", { max_drift: 0.5, recoveries: 1 }),
];

beforeEach(() => { window.location.hash = ""; });

describe("the guide", () => {
  it("explains what a square is, what the colour means and what the marks mean", async () => {
    show(api(ARMS));
    const guide = (await screen.findByText("How to read this page")).closest("details")!;
    expect(guide).toHaveTextContent("Each square is one run");
    expect(guide).toHaveTextContent("The colour is the highest drift the run reached");
    expect(guide).toHaveTextContent("0 means every rule held");
    expect(within(guide).getByRole("list", { name: "Marks on a square" })).toHaveTextContent("A dot means the run is flagged halted in the record");
    expect(within(guide).getByRole("list", { name: "Marks on a square" })).toHaveTextContent("A red frame");
    expect(within(guide).getByRole("list", { name: "Marks on a square" })).toHaveTextContent("A cyan frame");
    expect(guide).toHaveTextContent("Each contract sets its own threshold for acting");
  });

  it("can be collapsed", async () => {
    show(api(ARMS));
    const guide = (await screen.findByText("How to read this page")).closest("details")!;
    expect(guide).toHaveAttribute("open");
  });
});

describe("grouping by series", () => {
  it("groups runs named alike into series, with a summary each, by default", async () => {
    show(api(ARMS));
    const a = await screen.findByLabelText("Series arm-a");
    const b = screen.getByLabelText("Series arm-b");
    expect(a).toHaveTextContent("3 runs");
    expect(a).toHaveTextContent("Average peak drift 0.10");
    expect(a).toHaveTextContent("1 of 3 needed a correction");
    expect(b).toHaveTextContent("Average peak drift 0.62");
    expect(b).toHaveTextContent("3 of 3 needed a correction");
    expect(b).toHaveTextContent("1 of 3 halted");
    expect(within(b).getAllByRole("button")).toHaveLength(3);                             // one square per run
  });

  it("each square names its run and says what it is, so colour is never the only signal", async () => {
    show(api(ARMS));
    const b = await screen.findByLabelText("Series arm-b");
    expect(within(b).getByRole("button", { name: "arm-b-s1: peak drift 0.90, 2 corrections, halted" })).toBeInTheDocument();
    expect(within(b).getByRole("button", { name: "arm-b-s0: peak drift 0.45, 3 corrections" })).toBeInTheDocument();
  });

  it("switches to the plain grid and back", async () => {
    show(api(ARMS));
    await screen.findByLabelText("Series arm-a");
    fireEvent.click(screen.getByRole("radio", { name: "All runs" }));
    expect(screen.queryByLabelText("Series arm-a")).not.toBeInTheDocument();
    expect(document.querySelector("canvas")).not.toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "By series" }));
    expect(screen.getByLabelText("Series arm-a")).toBeInTheDocument();
  });

  it("offers no layout choice, and no groups, when the runs don't form several series", async () => {
    show(api([run("run-000001"), run("run-000002"), run("run-000003")]));
    await screen.findByLabelText("Fleet summary");
    expect(screen.queryByRole("radio", { name: "By series" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Series /)).not.toBeInTheDocument();
    expect(document.querySelector("canvas")).not.toBeNull();
  });
});

describe("explaining the selected run", () => {
  it("says in plain words what the peak means against this run's own contract threshold", async () => {
    show(api(ARMS));
    const b = await screen.findByLabelText("Series arm-b");
    fireEvent.click(within(b).getByRole("button", { name: /^arm-b-s0/ }));
    const panel = await screen.findByLabelText("Selected run");
    expect(await within(panel).findByText(/at or above this contract's threshold of 0.1/)).toBeInTheDocument();
    expect(panel).toHaveTextContent("3 corrections fired.");
    expect(panel).toHaveTextContent("One of 3 runs in arm-b, which averaged a peak drift of 0.62.");
    expect(within(panel).getByRole("link", { name: "Replay this run" })).toHaveAttribute("href", "#/run/arm-b-s0");
  });

  it("says when a run stayed below the contract's threshold", async () => {
    show(api(ARMS));
    fireEvent.click(within(await screen.findByLabelText("Series arm-a")).getByRole("button", { name: /^arm-a-s0/ }));
    expect(await within(screen.getByLabelText("Selected run")).findByText(/below this contract's threshold of 0.1/)).toBeInTheDocument();
  });

  it("mentions a halt", async () => {
    show(api(ARMS));
    fireEvent.click(within(await screen.findByLabelText("Series arm-b")).getByRole("button", { name: /^arm-b-s1/ }));
    expect(await within(screen.getByLabelText("Selected run")).findByText(/The run was flagged halted in the record/)).toBeInTheDocument();
  });

  it("makes no threshold claim when the contract can't be read", async () => {
    show(api(ARMS, null));
    fireEvent.click(within(await screen.findByLabelText("Series arm-b")).getByRole("button", { name: /^arm-b-s0/ }));
    const panel = screen.getByLabelText("Selected run");
    expect(await within(panel).findByText(/Peaked at 0.45 drift\./)).toBeInTheDocument();
    expect(panel).not.toHaveTextContent("contract's threshold");
  });

  it("the selected square is marked pressed, and picking another moves the selection", async () => {
    show(api(ARMS));
    const a = await screen.findByLabelText("Series arm-a");
    const first = within(a).getByRole("button", { name: /^arm-a-s0/ });
    fireEvent.click(first);
    expect(first).toHaveAttribute("aria-pressed", "true");
    const second = within(a).getByRole("button", { name: /^arm-a-s1/ });
    fireEvent.click(second);
    expect(second).toHaveAttribute("aria-pressed", "true");
    expect(first).toHaveAttribute("aria-pressed", "false");
  });
});
