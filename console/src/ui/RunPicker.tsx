import { useMemo } from "react";
import { hrefFor, type PageName } from "../lib/router";
import type { Run } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "./ApiContext";
import { StateView } from "./StateView";
import { BandBadge, shortHash } from "./format";

/** Runs that have a stored trace, featured demo runs first. */
export function useTracedRuns(): [ReturnType<typeof useResource<Run[]>>[0], () => void] {
  const api = useApi();
  const [res, reload] = useResource(async () => {
    // filtered server-side: a client-side filter over the top-N most drifted would hide traced runs
    const runs = await api.runs({ has_trace: true, limit: 500 });
    return runs
      .sort((a, b) => Number(b.run_id.startsWith("demo-")) - Number(a.run_id.startsWith("demo-")) || a.run_id.localeCompare(b.run_id));
  }, []);
  return [res, reload];
}

export function RunPicker({ page, title, intro }: { page: PageName; title: string; intro: string }) {
  const [res, reload] = useTracedRuns();
  const rows = useMemo(() => (res.status === "ready" ? res.data : []), [res]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          <p>{intro}</p>
        </div>
      </div>
      <StateView
        resource={res}
        reload={reload}
        label="Loading runs with traces"
        isEmpty={(d) => d.length === 0}
        empty={{
          title: "No runs with a stored trace",
          body: "Replay needs a recorded trace. Send traffic through the proxy with a contract header, or run make console-demo for simulated runs.",
        }}
      >
        {() => (
          <section className="panel" aria-label="Runs with traces">
            <header><h2>Choose a run</h2></header>
            <table>
              <thead>
                <tr><th>Run</th><th>Status</th><th className="r">Peak drift</th><th className="r">Corrections</th><th>Contract</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.run_id}>
                    <td><a className="mono" href={hrefFor(page, r.run_id)}>{r.run_id}</a></td>
                    <td><BandBadge drift={r.max_drift} /></td>
                    <td className="r num">{r.max_drift.toFixed(2)}</td>
                    <td className="r num">{r.recoveries}</td>
                    <td className="mono">{shortHash(r.contract_hash)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </StateView>
    </>
  );
}
