import { useMemo } from "react";
import type { Pack } from "../lib/types";
import { useResource } from "../lib/useResource";
import { useApi } from "../ui/ApiContext";
import { StateView } from "../ui/StateView";
import { shortHash } from "../ui/format";

/** An eval slot is a measurement or it is nothing. Null must never read as zero. */
export function EvalValue({ v }: { v: number | boolean | null | undefined }) {
  if (v === null || v === undefined) {
    return <span className="muted"><span aria-hidden="true">– </span>not measured</span>;
  }
  if (typeof v === "boolean") return <span>{v ? "Passed" : "Failed"}</span>;
  return <span className="num">{v > 0 ? "+" : ""}{v.toFixed(2)} pts</span>;
}

export function PacksPage() {
  const api = useApi();
  const [res, reload] = useResource(async () => {
    const [p, runs] = await Promise.all([api.packs(), api.runs({ limit: 10000 }).then((r) => r, () => null)]);
    // Exact model ids only. A simulated run (mock:qwen2.5-7b) is not a run on the real model,
    // so it must not be counted against that model's pack. null = the count couldn't be loaded.
    let use: Record<string, number> | null = null;
    if (runs) {
      use = {};
      for (const r of runs) use[r.model] = (use[r.model] ?? 0) + 1;
    }
    return { ...p, use };
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Packs</h1>
          <p>A pack holds the steering vectors for one open-weight model. Evaluation results appear here only once they have been measured on that model.</p>
        </div>
      </div>
      <StateView
        resource={res}
        reload={reload}
        label="Loading packs"
        isEmpty={(d) => d.packs.length === 0 && d.skipped.length === 0}
        empty={{
          title: "No packs found",
          body: "Build a starter pack with python packs/build_pack.py --synthetic --out packs/<model>/ and set OPENGUIDE_PACKS_DIR to the folder that contains it.",
        }}
      >
        {(d) => (
          <>
            {d.skipped.length > 0 && (
              <div className="notice" role="status">
                {d.skipped.length} {d.skipped.length === 1 ? "pack was" : "packs were"} skipped because its eval card couldn't be read: {d.skipped.join(", ")}.
              </div>
            )}
            {d.packs.map((p) => <PackRow key={p.name} p={p} runs={d.use === null ? null : (d.use[p.model_id] ?? 0)} />)}
          </>
        )}
      </StateView>
    </>
  );
}

function PackRow({ p, runs }: { p: Pack; runs: number | null }) {
  const ev = p.evals ?? {};
  const gains = useMemo(
    () => [...new Set([...Object.keys(ev.mmlu_delta_at_gain ?? {}), ...Object.keys(ev.gsm8k_delta_at_gain ?? {})])].sort(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [p],
  );
  const synthetic = p.status === "synthetic";
  return (
    <section className="panel" aria-label={`Pack for ${p.model_id}`}>
      <header>
        <h2>{p.model_id}</h2>
        <span className={`badge ${synthetic ? "warn" : ""}`}>{synthetic ? "Synthetic, for demos" : "Derived from the model"}</span>
        <span className="grow" />
        <span className="muted">{runs === null ? "Run count unavailable" : runs > 0 ? `${runs.toLocaleString()} runs recorded on this model` : "No runs recorded on this model"}</span>
      </header>
      <div className="body stack">
        <dl className="kv">
          <dt>Pack hash</dt><dd className="mono">{shortHash(p.pack_hash, 16)}</dd>
          <dt>Shape</dt><dd className="num">{p.layers} layers, {p.dim} dimensions</dd>
          <dt>Signals</dt><dd>{(p.signals ?? []).map((s) => <span className="chip" key={s}>{s}</span>)}</dd>
        </dl>
        {synthetic && (
          <p className="notice">
            These vectors are generated for demonstration. They were not derived from activations captured on {p.model_id}, so no capability claim applies.
          </p>
        )}
        <table>
          <thead><tr><th>Evaluation</th>{gains.map((g) => <th key={g} className="r">Gain {g}</th>)}<th className="r">Coherence</th></tr></thead>
          <tbody>
            <tr>
              <td>MMLU change</td>
              {gains.map((g) => <td key={g} className="r"><EvalValue v={ev.mmlu_delta_at_gain?.[g]} /></td>)}
              <td className="r">—</td>
            </tr>
            <tr>
              <td>GSM8K change</td>
              {gains.map((g) => <td key={g} className="r"><EvalValue v={ev.gsm8k_delta_at_gain?.[g]} /></td>)}
              <td className="r">—</td>
            </tr>
            <tr>
              <td>Generation coherence</td>
              {gains.map((g) => <td key={g} />)}
              <td className="r"><EvalValue v={ev.coherence_ok} /></td>
            </tr>
          </tbody>
        </table>
        {p.note && <p className="muted">{p.note}</p>}
      </div>
    </section>
  );
}
