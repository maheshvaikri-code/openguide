import { useMemo, useState } from "react";
import { excursionStarts, pickAxes, project } from "../lib/projection";
import { clampIndex, firstCorrection, parseStates } from "../lib/replay";
import { hrefFor } from "../lib/router";
import { parseThresholds, UNKNOWN_THRESHOLDS, type Thresholds } from "../lib/thresholds";
import type { StateRecord } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "../ui/ApiContext";
import { RunPicker } from "../ui/RunPicker";
import { Scene3D } from "../ui/Scene3D";
import { StateView } from "../ui/StateView";
import { BandBadge } from "../ui/format";

export default function TrajectoryPage({ runId }: { runId: string | null }) {
  if (!runId) {
    return (
      <RunPicker
        page="trajectory"
        title="Trajectory"
        intro="See a run as a path through three of its measured behaviors. The green box is where the contract says the agent should stay."
      />
    );
  }
  return <Trajectory runId={runId} />;
}

function Trajectory({ runId }: { runId: string }) {
  const api = useApi();
  const [res, reload] = useResource<{ states: StateRecord[]; noTrace: boolean; gates: Thresholds }>(async () => {
    const run = await api.run(runId);
    // the contract's own gates; if unreadable we draw no threshold rather than guess one
    const gates = await api.contract(run.contract_hash).then((c) => parseThresholds(c.contract)).catch(() => UNKNOWN_THRESHOLDS);
    if (!run.trace_cas_key) return { states: [], noTrace: true, gates }; // known to have nothing: don't ask for it
    return { states: parseStates((await api.trace(runId)).records).states, noTrace: false, gates };
  }, [runId]);
  const noTrace = res.status === "ready" && res.data.noTrace;
  return (
    <StateView
      resource={res}
      reload={reload}
      label="Loading trace"
      isEmpty={(d) => d.states.length === 0}
      empty={{
        title: noTrace ? "This run has no stored trace" : "No turns to plot",
        body: noTrace
          ? "The fleet index records that this run happened, but its full trace wasn't kept, so there is no path to draw."
          : "This run's trace has no behavioral-state records.",
        action: <a className="btn" href={hrefFor("trajectory")}>Choose a run with a trace</a>,
      }}
    >
      {(d) => <View runId={runId} states={d.states} gates={d.gates} />}
    </StateView>
  );
}

function View({ runId, states, gates }: { runId: string; states: StateRecord[]; gates: Thresholds }) {
  const projection = useMemo(() => project(states, pickAxes(states), gates.threshold), [states, gates.threshold]);
  const [index, setIndex] = useState(0);
  const i = clampIndex(index, projection.points.length);
  const p = projection.points[i]!;
  const starts = excursionStarts(projection.points);
  const firstFix = firstCorrection(states);
  const back = starts.length
    ? projection.points.findIndex((q, k) => q.turn > starts[0]! && !q.excursion && k > 0)
    : -1;
  const atOrAboveGate = projection.points.filter((q) => q.excursion).length;
  const peak = Math.max(0, ...projection.points.map((q) => q.drift));
  // Turns outside the drawn safe region (any axis outside its band), so the words match the box.
  const [sx, sy, sz] = projection.safe;
  const inBand = (v: number, [lo, hi]: [number, number]) => v >= lo && v <= hi;
  const outsideBox = projection.points.filter((q) => !(inBand(q.x, sx) && inBand(q.y, sy) && inBand(q.z, sz))).length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Trajectory: {runId}</h1>
          <p>Each turn is a point at (<span className="mono">{projection.axes.join(", ")}</span>). Drag to rotate, scroll to zoom.</p>
        </div>
        <span className="grow" />
        <a className="btn" href={hrefFor("run", runId)}>Replay</a>
        <a className="btn" href={hrefFor("audit", runId)}>Audit report</a>
      </div>

      <div className="split">
        <div className="stack">
          <Scene3D projection={projection} index={i} />
          <div className="controls">
            <label className="field" style={{ flex: 1 }}>
              Turn <span className="num">{p.turn}</span>
              <input type="range" min={0} max={projection.points.length - 1} value={i} onChange={(e) => setIndex(Number(e.target.value))}
                aria-valuetext={`Turn ${p.turn}, drift ${p.drift.toFixed(2)}`} />
            </label>
          </div>
          <div className="legend">
            <span><span style={{ color: "var(--rose)" }} aria-hidden="true">━</span> {projection.axes[0]}</span>
            <span><span style={{ color: "var(--green)" }} aria-hidden="true">━</span> {projection.axes[1]}</span>
            <span><span style={{ color: "var(--cyan)" }} aria-hidden="true">━</span> {projection.axes[2]}</span>
            <span><span style={{ color: "var(--green)" }} aria-hidden="true">▢</span> Safe region</span>
            <span><span style={{ color: "var(--red)" }} aria-hidden="true">●</span> Above threshold</span>
            <span><span style={{ color: "var(--cyan)" }} aria-hidden="true">◆</span> Correction fired</span>
          </div>
        </div>

        <aside className="stack">
          <section className="panel" aria-label="Summary of this path">
            <header><h2>What the path shows</h2></header>
            <div className="body stack">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                <li>
                  {gates.threshold === null
                    ? `Peak drift was ${peak.toFixed(2)}. This contract's drift threshold couldn't be read, so none is drawn.`
                    : starts.length === 0
                      ? `Drift never reached the contract's threshold of ${gates.threshold} (peak ${peak.toFixed(2)}).`
                      : `Drift first reached the contract's threshold of ${gates.threshold} at turn ${starts[0]}, and was at or above it for ${atOrAboveGate} ${atOrAboveGate === 1 ? "turn" : "turns"} in total.`}
                </li>
                <li>
                  {outsideBox === 0
                    ? "Every turn stayed inside the green safe region."
                    : `${outsideBox} of ${projection.points.length} turns were outside the green safe region.`}
                </li>
                <li>{firstFix < 0 ? "No correction fired." : `The first correction fired at turn ${states[firstFix]!.turn}.`}</li>
                {back > 0 && <li>It returned to the safe region at turn {projection.points[back]!.turn}.</li>}
              </ul>
            </div>
          </section>
          <section className="panel" aria-label="State at the selected turn">
            <header><h2>Turn {p.turn}</h2><span className="grow" /><BandBadge drift={p.drift} /></header>
            <dl className="kv body">
              <dt>{projection.axes[0]}</dt><dd className="num">{p.x.toFixed(2)}</dd>
              <dt>{projection.axes[1]}</dt><dd className="num">{p.y.toFixed(2)}</dd>
              <dt>{projection.axes[2]}</dt><dd className="num">{p.z.toFixed(2)}</dd>
              <dt>Drift</dt><dd className="num">{p.drift.toFixed(2)}</dd>
              <dt>Correction</dt><dd>{p.corrected ? "Fired this turn" : "None"}</dd>
            </dl>
            {p.gap && <p className="notice" style={{ margin: "0 16px 16px" }}>A sensor had no reading this turn, so its last value is shown.</p>}
          </section>
        </aside>
      </div>
    </>
  );
}
