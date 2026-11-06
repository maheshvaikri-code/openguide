import type { Run } from "./types";

/**
 * The experiment arm / batch a run belongs to, taken from its id by dropping a trailing SEED ("-s3") or a
 * long zero-padded counter ("-000123"): "real-shock-none-s3" -> "real-shock-none", "run-000123" -> "run".
 * A bare short number is NOT stripped, because it is as likely a parameter or a date as a counter
 * ("gpt-4", "sweep-gain-10", "run-2024-01-05" stay whole). A naming convention, not metadata: the proxy
 * records no arm, so this only groups runs that are named alike.
 */
export function seriesOf(runId: string): string {
  const base = runId.replace(/[-_](?:s\d+|\d{3,})$/, "");
  return base || runId;
}

export interface Group {
  name: string;
  runs: Run[];
  count: number;
  meanPeak: number;
  halted: number;
  corrected: number;     // runs in which at least one correction fired
  broken: number;        // stored traces whose hash chain does not verify
  unchecked: number;     // runs with no stored trace to re-check
}

export function groupRuns(runs: readonly Run[]): Group[] {
  const by = new Map<string, Run[]>();
  for (const r of runs) {
    const k = seriesOf(r.run_id);
    const list = by.get(k);
    if (list) list.push(r);
    else by.set(k, [r]);
  }
  return [...by.entries()]
    .map(([name, rs]) => ({
      name,
      runs: rs,
      count: rs.length,
      meanPeak: rs.reduce((s, r) => s + r.max_drift, 0) / rs.length,
      halted: rs.filter((r) => r.halted).length,
      corrected: rs.filter((r) => r.recoveries > 0).length,
      broken: rs.filter((r) => r.trace_cas_key && !r.verified).length,
      unchecked: rs.filter((r) => !r.trace_cas_key).length,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Grouping only helps when there are at least two series that each hold at least two runs. */
export function shouldGroup(groups: readonly Group[]): boolean {
  return groups.filter((g) => g.count >= 2).length >= 2;
}
