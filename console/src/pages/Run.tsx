import { useEffect, useMemo, useState } from "react";
import { BAND_LABEL, driftBand } from "../lib/heat";
import { measureKind, parseContractInfo, type ContractInfo } from "../lib/contractInfo";
import { clampIndex, correctionIndexes, firstCorrection, invariantIds, parseStates, parseSteers, parseTurns, readingSeries, signalIds } from "../lib/replay";
import { hrefFor } from "../lib/router";
import { atOrAbove, parseThresholds, UNKNOWN_THRESHOLDS, type Thresholds } from "../lib/thresholds";
import type { Run, StateRecord, SteerRecord, TurnRecord } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "../ui/ApiContext";
import { ConversationList } from "../ui/ConversationList";
import { RunPicker, useTracedRuns } from "../ui/RunPicker";
import { Scrubber } from "../ui/Scrubber";
import { Sparkline } from "../ui/Sparkline";
import { StateView } from "../ui/StateView";
import { TurnDetail } from "../ui/TurnDetail";
import { BandBadge, fmt, shortHash, VerifiedBadge } from "../ui/format";

export function RunPage({ runId }: { runId: string | null }) {
  if (!runId) {
    return (
      <RunPicker
        page="run"
        title="Run replay"
        intro="Scrub through a recorded run turn by turn, see where drift crossed the contract threshold, and jump to the moment a correction fired."
      />
    );
  }
  return <Replay runId={runId} />;
}

interface Loaded {
  run: Run;
  states: StateRecord[];
  ignored: number;
  verified: boolean;
  head: string;
  metadataOnly: boolean;
  noTrace: boolean; // the run is in the fleet index but no full trace was stored
  gates: Thresholds; // from the run's own contract; null fields mean the contract doesn't say
  info: ContractInfo; // the contract's rules, weights and response steps, for explaining each turn
  turns: Map<number, TurnRecord>; // what was said; empty unless the proxy captured content
  steers: Map<number, SteerRecord>; // turns that had activation steering; empty if the run never used it
}

function Replay({ runId }: { runId: string }) {
  const api = useApi();
  const [vs, setVs] = useState("");
  const [res, reload] = useResource<Loaded>(async () => {
    const run = await api.run(runId);
    // The contract's own gates; if it can't be read we draw no threshold rather than guess one.
    const body = await api.contract(run.contract_hash).then((c) => c.contract).catch(() => null);
    const gates = body === null ? UNKNOWN_THRESHOLDS : parseThresholds(body);
    const info = parseContractInfo(body);
    if (!run.trace_cas_key) {
      return { run, states: [], ignored: 0, verified: run.verified, head: run.trace_hash, metadataOnly: false, noTrace: true, gates, info, turns: new Map(), steers: new Map() };
    }
    const tr = await api.trace(runId);
    const { states, ignored } = parseStates(tr.records);
    return { run, states, ignored, verified: tr.verified, head: tr.head, metadataOnly: Boolean(tr.metadata_only), noTrace: false, gates, info, turns: parseTurns(tr.records), steers: parseSteers(tr.records) };
  }, [runId]);
  const [others] = useTracedRuns();
  const [baseRes] = useResource<StateRecord[]>(
    async () => (vs ? parseStates((await api.trace(vs)).records).states : []),
    [vs],
  );

  return (
    <StateView
      resource={res}
      reload={reload}
      label="Loading run and trace"
      isEmpty={(d) => d.states.length === 0}
      empty={
        res.status === "ready" && res.data.noTrace
          ? {
              title: "This run has no stored trace",
              body: "The fleet index records that this run happened, but its full trace wasn't kept, so there is nothing to replay. Runs captured through the proxy keep their trace.",
              action: <a className="btn" href={hrefFor("run")}>Choose a run with a trace</a>,
            }
          : {
              title: "This run has no recorded turns",
              body: "The trace exists but holds no behavioral-state records, so there is nothing to replay. Check that the run was governed by a contract.",
              action: <a className="btn" href={hrefFor("run")}>Choose another run</a>,
            }
      }
    >
      {(d) => (
        <ReplayView
          d={d}
          others={others.status === "ready" ? others.data.filter((r) => r.run_id !== runId) : []}
          vs={vs}
          setVs={setVs}
          baseline={baseRes.status === "ready" ? baseRes.data : undefined}
          baselineError={vs && baseRes.status === "error" ? baseRes.error.message : null}
        />
      )}
    </StateView>
  );
}

function ReplayView({
  d,
  others,
  vs,
  setVs,
  baseline,
  baselineError,
}: {
  d: Loaded;
  others: Run[];
  vs: string;
  setVs: (v: string) => void;
  baseline?: StateRecord[];
  baselineError: string | null;
}) {
  const { states } = d;
  const first = firstCorrection(states);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const cur = states[clampIndex(index, states.length)]!;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setIndex((i) => Math.min(i + 1, states.length - 1)), 260 / speed);
    return () => clearInterval(id);
  }, [playing, speed, states.length]);

  // stop at the end (kept out of the updater above so the updater stays pure)
  useEffect(() => {
    if (playing && index >= states.length - 1) setPlaying(false);
  }, [playing, index, states.length]);

  const signals = useMemo(() => signalIds(states), [states]);
  const invs = useMemo(() => invariantIds(states), [states]);
  const corrections = useMemo(() => correctionIndexes(states), [states]);
  const band = driftBand(cur.drift);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{d.run.run_id}</h1>
          <p>
            {d.run.model} at tier {d.run.tier.toUpperCase()}
            {d.steers.size > 0 && ` + T0 steering (on ${d.steers.size} ${d.steers.size === 1 ? "turn" : "turns"})`}
            , {states.length} turns,{" "}
            {corrections.length} {corrections.length === 1 ? "correction" : "corrections"}.
          </p>
        </div>
        <span className="grow" />
        <VerifiedBadge ok={d.verified} />
        <a className="btn" href={hrefFor("trajectory", d.run.run_id)}>Trajectory</a>
        <a className="btn" href={hrefFor("audit", d.run.run_id)}>Audit report</a>
      </div>

      {d.ignored > 0 && (
        <div className="notice" role="status">
          {d.ignored} {d.ignored === 1 ? "record was" : "records were"} not behavioral-state records and {d.ignored === 1 ? "is" : "are"} left out of the replay.
        </div>
      )}

      {baselineError && (
        <div className="notice bad" role="status">Couldn't load the comparison run: {baselineError} The timeline shows this run alone.</div>
      )}

      <section className="panel" aria-label="Replay timeline">
        <header>
          <h2>Timeline</h2>
          <span className="grow" />
          <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            Compare with
            <select value={vs} onChange={(e) => setVs(e.target.value)}>
              <option value="">Nothing</option>
              {others.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
            </select>
          </label>
        </header>
        <div className="body stack">
          <Scrubber states={states} baseline={baseline} threshold={d.gates.threshold} index={index} onIndex={(i) => { setPlaying(false); setIndex(i); }} />
          <div className="transport">
            <button className="btn primary" onClick={() => { if (index >= states.length - 1) setIndex(0); setPlaying((p) => !p); }}>
              {playing ? "Pause" : "Play"}
            </button>
            <button className="btn" disabled={first < 0} onClick={() => { setPlaying(false); setIndex(first); }}>
              {first < 0 ? "No correction fired" : `Jump to first correction (turn ${states[first]!.turn})`}
            </button>
            <label className="field" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              Speed
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                <option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option>
              </select>
            </label>
            <span className="muted" aria-live="polite">Turn <span className="num">{cur.turn}</span> of <span className="num">{states[states.length - 1]!.turn}</span></span>
          </div>
        </div>
      </section>

      <TurnDetail state={cur} turn={d.turns.get(cur.turn)} steer={d.steers.get(cur.turn)} info={d.info} anyContent={d.turns.size > 0} />

      <div className="split">
        <div className="stack">
          <ContractRules info={d.info} />

          <section className="panel" aria-label="Signals over turns">
            <header><h2>Signals and corrections</h2></header>
            <div className="body">
              <SignalStrip states={states} signals={signals} index={index} />
            </div>
          </section>

          <section className="panel" aria-label="Invariant readings">
            <header><h2>Invariant readings</h2></header>
            <div className="body stack">
              {invs.map((id) => (
                <div key={id}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <span className="mono">{id}</span>
                    <span className="num muted">{fmt(cur.invariants[id]?.reading)}</span>
                  </div>
                  <Sparkline
                    values={readingSeries(states, id)}
                    floor={states.find((s) => typeof s.invariants[id]?.floor === "number")?.invariants[id]?.floor}
                    marks={corrections}
                    at={index}
                    label={`${id} reading over turns`}
                  />
                </div>
              ))}
            </div>
          </section>

          <ConversationList states={states} turns={d.turns} index={index} info={d.info}
            onPick={(i) => { setPlaying(false); setIndex(i); }} />
        </div>

        <aside className="stack" aria-label={`State at turn ${cur.turn}`}>
          <section className="panel">
            <header><h2>Turn {cur.turn}</h2><span className="grow" /><BandBadge drift={cur.drift} /></header>
            <div className="body stack">
              <div className="figure"><b>{cur.drift.toFixed(2)}</b><span>drift ({BAND_LABEL[band].toLowerCase()})</span></div>
              {d.gates.threshold !== null ? (
                <p className="muted">
                  {atOrAbove(cur.drift, d.gates.threshold) ? "At or above" : "Below"} this contract's threshold of{" "}
                  <span className="num">{d.gates.threshold}</span>
                  {d.gates.halt !== null && <>; it halts the run at <span className="num">{d.gates.halt}</span></>}.
                </p>
              ) : (
                <p className="muted">This contract's threshold couldn't be read, so none is shown.</p>
              )}
              {cur.recovery_fired ? (
                <div className="notice">Correction fired: <b>{cur.recovery_fired.replace("_", "-")}</b>{cur.reanchored ? ". A re-statement of the contract was prepared for the next turn." : "."}</div>
              ) : (
                <p className="muted">No correction on this turn.</p>
              )}
              {Object.keys(cur.signals_active).length > 0 && (
                <div>
                  <h3>Signals active</h3>
                  {Object.entries(cur.signals_active).map(([k, g]) => <span className="chip" key={k}>{k} <span className="num">{g.toFixed(2)}</span></span>)}
                </div>
              )}
            </div>
          </section>
          <section className="panel">
            <header><h2>Record</h2></header>
            <dl className="kv body">
              <dt>Trace head</dt><dd className="mono">{shortHash(d.head, 16)}</dd>
              <dt>Contract</dt><dd><a href={hrefFor("contracts", d.run.contract_hash)}>{shortHash(d.run.contract_hash)}</a></dd>
              <dt>Peak drift</dt><dd className="num">{d.run.max_drift.toFixed(2)}</dd>
            </dl>
          </section>
        </aside>
      </div>
    </>
  );
}

function SignalStrip({ states, signals, index }: { states: readonly StateRecord[]; signals: string[]; index: number }) {
  const rows = [...signals, "re-anchor prepared", "correction"];
  const W = 440; // plotted width; with the 140px label column the viewBox stays near 1:1 on screen
  const rowH = 22;
  const cw = W / Math.max(states.length, 1);
  const L = 140;
  return (
    <svg viewBox={`0 0 ${W + L} ${rows.length * rowH + 4}`} style={{ width: "100%" }} role="img"
      aria-label={`Which signals were active on each turn, plus when a contract re-statement was prepared and when a correction fired. Currently at turn ${states[clampIndex(index, states.length)]?.turn ?? 0}.`}>
      {rows.map((r, ri) => (
        <g key={r} transform={`translate(0 ${ri * rowH})`}>
          <text x="0" y="15" fontSize="12" fill="var(--muted)">{r}</text>
          {states.map((s, i) => {
            const v = r === "correction" ? (s.recovery_fired ? 1 : 0) : r === "re-anchor prepared" ? (s.reanchored ? 1 : 0) : s.signals_active[r] ?? 0;
            if (!v) return null;
            const color = r === "correction" ? "var(--green)" : r === "re-anchor prepared" ? "var(--cyan)" : "var(--amber)";
            return <rect key={i} x={L + i * cw} y="2" width={Math.max(cw - 0.6, 1)} height={rowH - 4} fill={color} opacity={r === "correction" || r === "re-anchor prepared" ? 0.95 : 0.25 + 0.75 * Math.min(v, 1)} />;
          })}
        </g>
      ))}
      <line x1={L + index * cw + cw / 2} x2={L + index * cw + cw / 2} y1="0" y2={rows.length * rowH} stroke="var(--strong)" strokeWidth="1.5" />
    </svg>
  );
}

/** What the contract requires, so a viewer knows what the sensors are checking before reading results. */
function ContractRules({ info }: { info: ContractInfo }) {
  const rules = Object.values(info.rules);
  if (rules.length === 0 && info.boundaries.length === 0) return null;
  return (
    <details className="panel" open>
      <summary className="panel-summary"><h2>What this contract requires</h2></summary>
      <div className="body stack">
        {info.persona && <p>Persona: <b>{info.persona}</b></p>}
        {info.boundaries.length > 0 && (
          <div>
            <h3>Rules restated to the model when it drifts</h3>
            <ul className="plain">{info.boundaries.map((b) => <li key={b}>{b}</li>)}</ul>
          </div>
        )}
        {rules.length > 0 && (
          <div>
            <h3>What is measured</h3>
            <table className="detect">
              <thead><tr><th>Rule</th><th>Measured by</th><th className="r">Must be at least</th><th className="r">Weight</th></tr></thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td>{measureKind(r.measure) ?? "unknown"}{r.hard && <span className="muted"> (hard rule: pass or fail)</span>}</td>
                    <td className="r num">{r.floor === null ? "–" : r.floor.toFixed(2)}</td>
                    <td className="r num">{r.weight === null ? "–" : r.weight.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  );
}
