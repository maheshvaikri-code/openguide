import { driftColor } from "../lib/heat";
import type { Group } from "../lib/series";

const MAX_SQUARES = 150;

/**
 * Runs grouped into series (experiment arms or batches, taken from how the runs are named). Each series
 * gets a one-line summary and its runs as squares, so arms can be compared at a glance.
 */
export function SeriesView({
  groups,
  selectedId,
  newIds,
  filtered,
  onSelect,
  onOpen,
}: {
  /** True when filters are narrowing the list: a series' figures then describe only the runs shown. */
  filtered: boolean;
  groups: readonly Group[];
  selectedId: string | null;
  newIds: ReadonlySet<string>;
  onSelect: (runId: string) => void;
  onOpen: (runId: string) => void;
}) {
  return (
    <div className="stack" aria-label="Runs grouped by series">
      {filtered && (
        <p className="notice" role="status">
          Filters are on, so each series below shows only the runs that match them, and its averages and counts
          cover just those runs.
        </p>
      )}
      {groups.map((g) => (
        <section key={g.name} className="panel series" aria-label={`Series ${g.name}`}>
          <header>
            <h2 className="mono">{g.name}</h2>
            <span className="grow" />
            <span className="muted">{g.count} {g.count === 1 ? "run" : "runs"}{filtered ? " shown" : ""}</span>
          </header>
          <div className="body stack">
            <p className="series-summary">
              Average peak drift <b className="num">{g.meanPeak.toFixed(2)}</b>
              {" · "}
              {g.corrected} of {g.count} needed a correction
              {" · "}
              {g.halted} of {g.count} halted
              {g.broken > 0 && <span style={{ color: "var(--red)" }}>{" · "}{g.broken} with a broken trace chain</span>}
            </p>
            <div className="squares" role="group" aria-label={`Runs in ${g.name}`}>
              {g.runs.slice(0, MAX_SQUARES).map((r) => {
                // marks drawn as outlines are also said in words, so nobody has to rely on colour
                const marks = `${Boolean(r.trace_cas_key) && !r.verified ? ", trace chain broken" : ""}`
                  + `${newIds.has(r.run_id) ? ", arrived since you opened this page" : ""}`;
                return (
                <button
                  key={r.run_id}
                  type="button"
                  className="sq"
                  data-selected={r.run_id === selectedId}
                  data-new={newIds.has(r.run_id)}
                  data-broken={Boolean(r.trace_cas_key) && !r.verified}
                  style={{ background: driftColor(r.max_drift) }}
                  aria-pressed={r.run_id === selectedId}
                  aria-label={`${r.run_id}: peak drift ${r.max_drift.toFixed(2)}, ${r.recoveries} ${r.recoveries === 1 ? "correction" : "corrections"}${r.halted ? ", halted" : ""}${marks}`}
                  title={`${r.run_id}\npeak drift ${r.max_drift.toFixed(2)} · ${r.recoveries} corrections · ${r.turns} turns${marks.replaceAll(", ", " · ")}`}
                  onClick={() => onSelect(r.run_id)}
                  onDoubleClick={() => onOpen(r.run_id)}
                >
                  {r.halted && <span className="halt-dot" aria-hidden="true" />}
                </button>
                );
              })}
            </div>
            {g.count > MAX_SQUARES && <p className="muted">Showing the first {MAX_SQUARES} of {g.count.toLocaleString()} runs in this series.</p>}
          </div>
        </section>
      ))}
    </div>
  );
}
