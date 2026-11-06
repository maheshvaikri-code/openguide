import { Fragment, useMemo, useState } from "react";
import { parseStates } from "../lib/replay";
import { hrefFor } from "../lib/router";
import type { Run, StateRecord, TraceResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "../ui/ApiContext";
import { StateView } from "../ui/StateView";
import { BandBadge, shortHash, VerifiedBadge } from "../ui/format";

const FLEET_LIMIT = 10000;

export function AuditPage({ runId }: { runId: string | null }) {
  return runId ? <Report runId={runId} /> : <Search />;
}

function Search() {
  const api = useApi();
  const [q, setQ] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [res, reload] = useResource(() => api.runs({ limit: FLEET_LIMIT }), []);
  const rows = useMemo(() => {
    const all = res.status === "ready" ? res.data : [];
    const needle = q.trim().toLowerCase();
    return all
      .filter((r) => (!needle || r.run_id.toLowerCase().includes(needle) || r.contract_hash.includes(needle)) && (!failedOnly || (r.trace_cas_key && !r.verified)))
      .slice(0, 200);
  }, [res, q, failedOnly]);
  const total = res.status === "ready" ? res.data.length : 0;
  const broken = res.status === "ready" ? res.data.filter((r) => r.trace_cas_key && !r.verified).length : 0;
  const unchecked = res.status === "ready" ? res.data.filter((r) => !r.trace_cas_key).length : 0;
  const capped = total >= FLEET_LIMIT;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit</h1>
          <p>Find a run, check that its record has not been altered, and produce a report you can print or save as PDF.</p>
        </div>
      </div>
      <form className="controls" onSubmit={(e) => e.preventDefault()} role="search" aria-label="Find a run">
        <label className="field">
          Run id or contract hash
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="demo-governed-sparse" />
        </label>
        <label className="check">
          <input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} />
          Only runs with a broken chain
        </label>
      </form>
      <StateView
        resource={res}
        reload={reload}
        label="Loading runs"
        isEmpty={(d) => d.length === 0}
        empty={{ title: "No runs to audit yet", body: "Runs appear here once traffic has passed through the proxy under a contract." }}
      >
        {() => (
          <section className="panel" aria-label="Search results">
            <header>
              <h2>{rows.length === 0 ? "No matches" : `${rows.length} ${rows.length === 1 ? "run" : "runs"} shown`}</h2>
              <span className="muted">
                {capped ? `First ${total.toLocaleString()} runs by drift` : `${total.toLocaleString()} in the fleet`}; {broken} with a broken chain; {unchecked.toLocaleString()} with no stored trace to re-check
              </span>
            </header>
            {rows.length === 0 ? (
              <div className="state"><p>No run matches that search. Check the id, or clear the filter.</p></div>
            ) : (
              <table>
                <thead><tr><th>Run</th><th>Chain</th><th className="r">Peak drift</th><th>Contract</th><th>Trace head</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.run_id}>
                      <td><a className="mono" href={hrefFor("audit", r.run_id)}>{r.run_id}</a></td>
                      <td><VerifiedBadge ok={r.verified} stored={Boolean(r.trace_cas_key)} /></td>
                      <td className="r num">{r.max_drift.toFixed(2)}</td>
                      <td className="mono">{shortHash(r.contract_hash)}</td>
                      <td className="mono">{shortHash(r.trace_hash, 12)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )}
      </StateView>
    </>
  );
}

interface Loaded { run: Run; tr: TraceResponse; states: StateRecord[] }

/** "record 3 was changed" -> "Record 3 was changed." */
export function sentence(s: string): string {
  const t = s.trim();
  return t ? `${t[0]!.toUpperCase()}${t.slice(1)}${/[.!?]$/.test(t) ? "" : "."}` : "";
}

function Report({ runId }: { runId: string }) {
  const api = useApi();
  const [res, reload] = useResource<Loaded | { run: Run; tr: null }>(async () => {
    const run = await api.run(runId);
    if (!run.trace_cas_key) return { run, tr: null as null };
    const tr = await api.trace(runId);
    return { run, tr, states: parseStates(tr.records).states };
  }, [runId]);

  return (
    <StateView
      resource={res}
      reload={reload}
      label="Verifying the trace"
      empty={{ title: "Nothing to report", body: "" }}
    >
      {(d) => (d.tr ? <Full d={d as Loaded} /> : <NoTrace run={d.run} />)}
    </StateView>
  );
}

function NoTrace({ run }: { run: Run }) {
  return (
    <>
      <div className="page-head"><div><h1>Audit report: {run.run_id}</h1></div></div>
      <div className="panel state">
        <span className="glyph" aria-hidden="true">○</span>
        <h2>No stored trace for this run</h2>
        <p>
          The fleet index records a trace head ({shortHash(run.trace_hash, 12)}) but the full record was not kept,
          so the chain can't be re-checked. Runs captured through the proxy keep their trace.
        </p>
        <a className="btn" href={hrefFor("audit")}>Back to search</a>
      </div>
    </>
  );
}

function Full({ d }: { d: Loaded }) {
  const { run, tr, states } = d;
  const chain = tr.chain ?? { ok: tr.verified, checked: tr.records?.length ?? 0, break_at: null, reason: tr.verified ? null : "the chain does not verify" };
  const ok = tr.verified && chain.ok;
  const events = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of tr.records ?? []) c[String(r["ev"] ?? "UNKNOWN")] = (c[String(r["ev"] ?? "UNKNOWN")] ?? 0) + 1;
    return c;
  }, [tr]);
  const actions = useMemo(() => {
    const c: Record<string, number> = {};
    for (const s of states) if (s.recovery_fired) c[s.recovery_fired] = (c[s.recovery_fired] ?? 0) + 1;
    return c;
  }, [states]);
  const corrections = states.filter((s) => s.recovery_fired);
  const m = tr.manifest as Record<string, unknown>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit report: {run.run_id}</h1>
          <p>Generated by the OpenGuide Console from the stored trace. The chain was re-checked by the proxy when you opened this page.</p>
        </div>
        <span className="grow" />
        <button className="btn primary no-print" onClick={() => window.print()}>Print or save as PDF</button>
        <a className="btn no-print" href={hrefFor("run", run.run_id)}>Replay</a>
      </div>

      <div className={`verdict ${ok ? "ok" : "bad"}`} role="status">
        <span className="mark" aria-hidden="true">{ok ? "✓" : "✕"}</span>
        <div className="stack">
          <h2>{ok ? "Hash chain consistent: no record changed after it was written" : "Hash chain broken: this record no longer matches itself"}</h2>
          <p>
            {ok
              ? `All ${chain.checked} records chain back to the run manifest, and the final hash matches the stored head.`
              : `${sentence(chain.reason ?? "the chain does not verify")}${chain.checked > 0 ? ` The first ${chain.checked} ${chain.checked === 1 ? "record links" : "records link"} correctly.` : ""} Treat this run's account of what happened as unreliable.`}
          </p>
          <p className="muted">
            This shows the record is internally consistent. It does not prove who wrote it: the head is stored with the
            records, so anyone able to rewrite the whole store could rewrite the chain as well. Anchor or sign the head
            outside this system if you need that guarantee.
          </p>
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <section className="panel">
            <header><h2>Run</h2><span className="grow" /><VerifiedBadge ok={ok} /></header>
            <dl className="kv body">
              <dt>Run id</dt><dd className="mono">{run.run_id}</dd>
              <dt>Model</dt><dd className="mono">{String(m["model"] ?? run.model)}</dd>
              <dt>Tier</dt><dd>{run.tier.toUpperCase()}</dd>
              <dt>Contract</dt><dd><a className="mono" href={hrefFor("contracts", run.contract_hash)}>{run.contract_hash}</a></dd>
              <dt>Runtime</dt><dd className="mono">{String(m["runtime"] ?? "not recorded")}</dd>
              <dt>Seed</dt><dd className="num">{String(m["seed"] ?? "not recorded")}</dd>
              <dt>Simulated</dt><dd>{m["simulated"] === true ? "Yes. The agent's behavior was simulated; the control path was real." : m["simulated"] === false ? "No" : "Not recorded"}</dd>
              <dt>Trace head</dt><dd className="mono">{tr.head}</dd>
              <dt>Records</dt><dd className="num">{tr.records?.length ?? chain.checked}</dd>
            </dl>
          </section>

          <section className="panel">
            <header><h2>Corrections</h2><span className="muted">{corrections.length} in {states.length} turns</span></header>
            {corrections.length === 0 ? (
              <div className="state"><p>No correction fired in this run.</p></div>
            ) : (
              <table>
                <thead><tr><th className="r">Turn</th><th>Action</th><th className="r">Drift</th><th>Status</th></tr></thead>
                <tbody>
                  {corrections.map((s) => (
                    <tr key={s.turn}>
                      <td className="r num">{s.turn}</td>
                      <td>{s.recovery_fired!.replace("_", "-")}</td>
                      <td className="r num">{s.drift.toFixed(2)}</td>
                      <td><BandBadge drift={s.drift} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>

        <aside className="stack">
          <section className="panel">
            <header><h2>Summary</h2></header>
            <dl className="kv body">
              <dt>Peak drift</dt><dd className="num">{run.max_drift.toFixed(2)}</dd>
              <dt>Halted</dt><dd>{run.halted ? "Yes" : "No"}</dd>
              {Object.entries(actions).map(([a, n]) => (<Fragment key={a}><dt>{a.replace("_", "-")}</dt><dd className="num">{n}</dd></Fragment>))}
              <dt>Sensor gaps</dt><dd className="num">{states.filter((s) => s.sensor_gaps.length).length} turns</dd>
              <dt>Hard check failures</dt><dd className="num">{states.filter((s) => s.validation_failures.length).length} turns</dd>
            </dl>
          </section>
          <section className="panel">
            <header><h2>Record types</h2></header>
            <dl className="kv body">
              {Object.entries(events).map(([k, n]) => (<Fragment key={k}><dt className="mono">{k}</dt><dd className="num">{n}</dd></Fragment>))}
            </dl>
          </section>
          <p className="muted">To check this independently of the Console, verify the trace against the format in <code>spec/trace/README.md</code>; <code>python spec/conformance/run_conformance.py</code> checks that an implementation reproduces the specification's hashes.</p>
        </aside>
      </div>
    </>
  );
}
