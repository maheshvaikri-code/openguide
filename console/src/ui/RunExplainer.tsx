import { describeRun, parseContractInfo, responseGate } from "../lib/contractInfo";
import { driftColor } from "../lib/heat";
import { parseStates, parseSteers } from "../lib/replay";
import { hrefFor } from "../lib/router";
import type { Group } from "../lib/series";
import { summarizeRun } from "../lib/runSummary";
import type { Run, StateRecord } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "./ApiContext";
import { BandBadge, VerifiedBadge } from "./format";

type TraceInfo = { states: StateRecord[]; steered: number } | null;

/**
 * Everything that explains one square, shown when it is selected: why it has its colour, what the marks on it
 * mean, what was actually detected in the run (read from its own trace), and its details. Each section can be
 * collapsed.
 */
export function RunExplainer({
  run,
  isNew,
  series,
  filtered,
  contractName,
}: {
  run: Run;
  isNew: boolean;
  series: Group | undefined;
  filtered: boolean;
  contractName: string;
}) {
  const api = useApi();
  const [contract] = useResource(async () => parseContractInfo((await api.contract(run.contract_hash)).contract), [run.contract_hash]);
  // an unreadable contract just means we make no claims that need it
  const info = contract.status === "ready" ? contract.data : parseContractInfo(null);
  const gate = responseGate(info);

  const [trace] = useResource<TraceInfo>(
    async () => {
      if (!run.trace_cas_key) return null;
      const { records } = await api.trace(run.run_id);
      return { states: parseStates(records).states, steered: parseSteers(records).size };
    },
    [run.run_id, run.trace_cas_key],
  );
  const broken = Boolean(run.trace_cas_key) && !run.verified;
  const steered = trace.status === "ready" && trace.data ? trace.data.steered : 0;

  return (
    <div className="stack">
      <div><BandBadge drift={run.max_drift} /> <VerifiedBadge ok={run.verified} stored={Boolean(run.trace_cas_key)} /></div>
      <p>{describeRun(run, gate)}</p>

      <details className="explain" open>
        <summary><h3>Why this colour</h3></summary>
        <div className="stack">
          <p>
            <span className="swatch inline" style={{ background: driftColor(run.max_drift) }} aria-hidden="true" />
            The colour is the highest drift this run reached, <b className="num">{run.max_drift.toFixed(2)}</b>. Drift
            is how far the run fell short of its contract's rules on a turn: for each rule, the gap below its minimum
            times its weight, added up and capped at 1. <b>0 means every rule held.</b>
          </p>
          {gate !== null && (
            <p className="muted">
              This contract starts responding at drift {gate}, so {run.max_drift >= gate ? "this run crossed it" : "this run never reached it"}.
              Other contracts set their own gate, so the same colour can mean something different on another run.
            </p>
          )}
          {(run.halted || broken || isNew) && (
            <ul className="key" aria-label="Marks on this square">
              {run.halted && (
                <li><span className="swatch halted" aria-hidden="true" /><span><b>A dark dot:</b> the run is flagged halted in the record. The proxy records a halt; it does not itself block later requests.</span></li>
              )}
              {broken && (
                <li><span className="swatch broken" aria-hidden="true" /><span><b>A red frame:</b> this run's trace no longer verifies, so it was altered after it was written.</span></li>
              )}
              {isNew && (
                <li><span className="swatch fresh" aria-hidden="true" /><span><b>A cyan frame:</b> this run arrived while you were watching.</span></li>
              )}
            </ul>
          )}
        </div>
      </details>

      <details className="explain" open>
        <summary><h3>What was detected in this run</h3></summary>
        <Detected run={run} trace={trace} info={info} />
      </details>

      <details className="explain">
        <summary><h3>Run details</h3></summary>
        <dl className="kv">
          <dt>Peak drift</dt><dd className="num">{run.max_drift.toFixed(2)}</dd>
          <dt>Corrections</dt><dd className="num">{run.recoveries}</dd>
          <dt>Flagged halted</dt><dd>{run.halted ? "Yes" : "No"}</dd>
          <dt>Turns</dt><dd className="num">{run.turns}</dd>
          <dt>Model</dt><dd className="mono">{run.model}</dd>
          <dt>Tier</dt><dd>{run.tier.toUpperCase()}</dd>
          {steered > 0 && (<><dt>Steering</dt><dd>T0 on {steered} {steered === 1 ? "turn" : "turns"}</dd></>)}
          <dt>Contract</dt><dd><a href={hrefFor("contracts", run.contract_hash)}>{contractName}</a></dd>
        </dl>
        {series && series.count > 1 && (
          <p className="muted" style={{ marginTop: 8 }}>
            One of {series.count} {filtered ? "runs shown" : "runs"} named <span className="mono">{series.name}…</span>,
            which averaged a peak drift of {series.meanPeak.toFixed(2)}.
          </p>
        )}
      </details>

      <div className="controls">
        <a className="btn primary" href={hrefFor("run", run.run_id)}>Replay this run</a>
        <a className="btn" href={hrefFor("audit", run.run_id)}>Audit</a>
      </div>
    </div>
  );
}

function Detected({
  run,
  trace,
  info,
}: {
  run: Run;
  trace: ReturnType<typeof useResource<TraceInfo>>[0];
  info: ReturnType<typeof parseContractInfo>;
}) {
  if (!run.trace_cas_key) {
    return <p className="muted">This run is in the fleet index only. Its full trace wasn't kept, so what was detected turn by turn isn't available.</p>;
  }
  if (trace.status === "loading") {
    return <div role="status" className="stack"><span className="sr-only">Loading what was detected…</span><div className="skeleton" style={{ width: "80%" }} /><div className="skeleton" style={{ width: "60%" }} /></div>;
  }
  if (trace.status === "error") {
    return <p className="notice bad" role="alert">Couldn't load this run's trace: {trace.error.message}</p>;
  }
  const states = trace.data?.states ?? [];
  if (states.length === 0) return <p className="muted">The trace holds no recorded turns.</p>;

  const s = summarizeRun(states, info);
  return (
    <div className="stack">
      <ul className="plain">
        <li>
          {s.gate !== null
            ? `Drift was at or above ${s.gate} on ${s.atOrAbove} of ${s.turns} turns.`
            : `${s.turns} turns were recorded. This contract's gate couldn't be read, so none is used here.`}
        </li>
        <li>{s.firstCorrection !== null ? `The first correction fired at turn ${s.firstCorrection}.` : "No correction fired."}</li>
        {s.firstCorrection !== null && s.gate !== null && (
          <li>
            {s.recoveredAt !== null
              ? `Drift was back below ${s.gate} at turn ${s.recoveredAt}, ${s.recoveredAt - s.firstCorrection} ${s.recoveredAt - s.firstCorrection === 1 ? "turn" : "turns"} after the first correction.`
              : `Drift did not come back below ${s.gate} before the run ended.`}
          </li>
        )}
        {s.gapTurns > 0 && <li>No reading was produced on {s.gapTurns} {s.gapTurns === 1 ? "turn" : "turns"}.</li>}
      </ul>
      <table className="detect" aria-label="Rules across this run">
        <thead><tr><th>Rule</th><th>Missed on</th><th className="r">Lowest</th></tr></thead>
        <tbody>
          {s.rules.map((r) => (
            <tr key={r.id} data-missed={r.missed > 0}>
              <td>
                <span className="mono">{r.id}</span>
                {r.kind && <div className="muted">{r.kind}</div>}
              </td>
              <td>
                {r.scored === 0
                  ? <span className="muted">never scored</span>
                  : r.missed > 0
                    ? <span style={{ color: "var(--red)" }}><span aria-hidden="true">▲ </span>{r.missed} of {r.scored} turns</span>
                    : <span style={{ color: "var(--green)" }}><span aria-hidden="true">✓ </span>never ({r.scored} turns)</span>}
              </td>
              <td className="r num">{r.lowest === null ? "–" : r.lowest.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
