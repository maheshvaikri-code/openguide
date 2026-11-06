import { useMemo, useRef, useState } from "react";
import { hrefFor } from "../lib/router";
import type { Run } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "../ui/ApiContext";
import { HeatField } from "../ui/HeatField";
import { StateView } from "../ui/StateView";
import { BandBadge, shortHash, VerifiedBadge } from "../ui/format";

/** Peak drift at which the fleet summary starts counting a run as high-drift. A reading aid, not a contract threshold. */
const HIGH_DRIFT = 0.3;

const open = (id: string) => {
  window.location.hash = hrefFor("run", id);
};

export function FleetPage() {
  const api = useApi();
  const [contract, setContract] = useState("");
  const [model, setModel] = useState("");
  const [minDrift, setMinDrift] = useState(0);
  const [haltedOnly, setHaltedOnly] = useState(false);
  const [live, setLive] = useState(true);
  // Selection is by run id, not list position: the list is ordered by drift and polled, so a
  // position would silently point at a different run when new ones arrive.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const firstSeen = useRef<Set<string> | null>(null);

  const [contracts] = useResource(() => api.contracts().catch(() => []), []);
  const [res, reload] = useResource(
    () =>
      api.runs({
        contract: contract || undefined,
        min_drift: minDrift > 0 ? minDrift : undefined,
        halted: haltedOnly ? true : undefined,
      }),
    [contract, minDrift, haltedOnly],
    live ? 3000 : undefined,
  );

  const all: Run[] = res.status === "ready" ? res.data : [];
  // options come from the loaded runs plus the current choice, so a selected model never vanishes
  const models = useMemo(() => [...new Set([...all.map((r) => r.model), ...(model ? [model] : [])])].sort(), [all, model]);
  const runs = useMemo(() => (model ? all.filter((r) => r.model === model) : all), [all, model]);

  // remember what was on screen when the page first filled, so live additions stand out
  if (res.status === "ready" && firstSeen.current === null) firstSeen.current = new Set(all.map((r) => r.run_id));
  const newIds = useMemo(
    () => (firstSeen.current ? new Set(all.filter((r) => !firstSeen.current!.has(r.run_id)).map((r) => r.run_id)) : new Set<string>()),
    [all],
  );

  const stats = useMemo(
    () => ({
      halted: runs.filter((r) => r.halted).length,
      high: runs.filter((r) => r.max_drift >= HIGH_DRIFT).length,
      broken: runs.filter((r) => r.trace_cas_key && !r.verified).length,
      unchecked: runs.filter((r) => !r.trace_cas_key).length,
    }),
    [runs],
  );
  const selected = selectedId === null ? -1 : runs.findIndex((r) => r.run_id === selectedId);
  const filtered = Boolean(contract || model || minDrift > 0 || haltedOnly);
  const sel = selected >= 0 ? runs[selected] : undefined;
  const contractName = (h: string) =>
    (contracts.status === "ready" && contracts.data.find((c) => c.hash === h)?.name) || `contract ${shortHash(h)}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Fleet</h1>
          <p>Every run, coloured by how far it drifted from its contract. Select a cell to inspect it; open it to replay what happened.</p>
        </div>
      </div>

      <form className="controls" onSubmit={(e) => e.preventDefault()} aria-label="Fleet filters">
        <label className="field">
          Contract
          <select value={contract} onChange={(e) => { setContract(e.target.value); setSelectedId(null); }}>
            <option value="">All contracts</option>
            {contracts.status === "ready" && contracts.data.map((c) => (
              <option key={c.hash} value={c.hash}>{c.name ?? "Unnamed contract"} {c.version ?? ""}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Model
          <select value={model} onChange={(e) => { setModel(e.target.value); setSelectedId(null); }}>
            <option value="">All models</option>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <label className="field">
          Minimum peak drift: <span className="num">{minDrift.toFixed(2)}</span>
          <input type="range" min={0} max={0.8} step={0.05} value={minDrift}
            onChange={(e) => { setMinDrift(Number(e.target.value)); setSelectedId(null); }} />
        </label>
        <label className="check">
          <input type="checkbox" checked={haltedOnly} onChange={(e) => { setHaltedOnly(e.target.checked); setSelectedId(null); }} />
          Halted runs only
        </label>
        <label className="check">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Live updates
        </label>
      </form>

      <StateView
        resource={res}
        reload={reload}
        label="Loading runs"
        isEmpty={() => runs.length === 0}
        empty={{
          title: filtered ? "No runs match these filters" : "No runs yet",
          body: filtered
            ? "Lower the minimum drift or clear the contract and model filters."
            : "Send traffic through the proxy with an X-OpenGuide-Contract header, or run make console-demo to load simulated data.",
          action: filtered ? (
            <button className="btn" onClick={() => { setContract(""); setModel(""); setMinDrift(0); setHaltedOnly(false); }}>
              Clear filters
            </button>
          ) : undefined,
        }}
      >
        {() => (
          <>
            <div className="figures" aria-label="Fleet summary">
              <div className="figure"><b>{runs.length.toLocaleString()}</b><span>runs shown</span></div>
              <div className="figure"><b>{stats.high.toLocaleString()}</b><span>peaked at {HIGH_DRIFT.toFixed(2)} drift or more</span></div>
              <div className="figure"><b>{stats.halted.toLocaleString()}</b><span>halted</span></div>
              <div className="figure"><b>{stats.broken.toLocaleString()}</b><span>with a broken trace chain</span></div>
              {stats.unchecked > 0 && <div className="figure"><b>{stats.unchecked.toLocaleString()}</b><span>with no stored trace to re-check</span></div>}
              {newIds.size > 0 && <div className="figure"><b>{newIds.size}</b><span>new since you opened this page</span></div>}
            </div>

            <div className="split">
              <div className="stack">
                <div className="well">
                  <HeatField runs={runs} selected={selected} newIds={newIds} onSelect={(i) => setSelectedId(runs[i]?.run_id ?? null)}
                    onOpen={(i) => runs[i] && open(runs[i].run_id)} />
                </div>
                <div className="legend" aria-label="Legend">
                  <span>Peak drift</span><span className="ramp" aria-hidden="true" />
                  <span className="num">0</span><span>low</span>
                  <span className="num">1</span><span>high</span>
                  <span>Each contract sets its own threshold; see a run for its contract's.</span>
                  <span>Dot: halted. Red frame: trace chain broken. Cyan frame: arrived while you watched.</span>
                </div>
              </div>

              <aside className="panel" aria-label="Selected run">
                <header><h2>{sel ? sel.run_id : "No run selected"}</h2></header>
                <div className="body stack">
                  {sel ? (
                    <>
                      <div><BandBadge drift={sel.max_drift} /> <VerifiedBadge ok={sel.verified} stored={Boolean(sel.trace_cas_key)} /></div>
                      <dl className="kv">
                        <dt>Peak drift</dt><dd className="num">{sel.max_drift.toFixed(2)}</dd>
                        <dt>Corrections</dt><dd className="num">{sel.recoveries}</dd>
                        <dt>Halted</dt><dd>{sel.halted ? "Yes" : "No"}</dd>
                        <dt>Turns</dt><dd className="num">{sel.turns}</dd>
                        <dt>Model</dt><dd className="mono">{sel.model}</dd>
                        <dt>Tier</dt><dd>{sel.tier.toUpperCase()}</dd>
                        <dt>Contract</dt><dd><a href={hrefFor("contracts", sel.contract_hash)}>{contractName(sel.contract_hash)}</a></dd>
                      </dl>
                      <div className="controls">
                        <a className="btn primary" href={hrefFor("run", sel.run_id)}>Replay this run</a>
                        <a className="btn" href={hrefFor("audit", sel.run_id)}>Audit</a>
                      </div>
                      {!sel.trace_cas_key && (
                        <p className="muted">This run is in the fleet index only, so there is no stored trace to replay.</p>
                      )}
                    </>
                  ) : (
                    <p className="muted">Hover the field to preview a run, click to pin it, or use the arrow keys.</p>
                  )}
                </div>
              </aside>
            </div>

            <section className="panel" aria-label="Most drifted runs">
              <header><h2>Most drifted runs</h2></header>
              <table>
                <thead>
                  <tr><th>Run</th><th>Status</th><th className="r">Peak drift</th><th className="r">Corrections</th><th>Model</th><th>Trace</th></tr>
                </thead>
                <tbody>
                  {runs.slice(0, 8).map((r, i) => (
                    <tr key={r.run_id} data-active={selected === i}>
                      <td><a className="mono" href={hrefFor(r.trace_cas_key ? "run" : "audit", r.run_id)}>{r.run_id}</a></td>
                      <td><BandBadge drift={r.max_drift} /></td>
                      <td className="r num">{r.max_drift.toFixed(2)}</td>
                      <td className="r num">{r.recoveries}</td>
                      <td className="mono">{r.model}</td>
                      <td><VerifiedBadge ok={r.verified} stored={Boolean(r.trace_cas_key)} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </>
        )}
      </StateView>
    </>
  );
}
