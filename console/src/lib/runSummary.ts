import { detectionRows, responseGate, type ContractInfo } from "./contractInfo";
import type { StateRecord } from "./types";

export interface RuleTally {
  id: string;
  kind: string | null;
  scored: number;   // turns the rule had a reading and was checked
  missed: number;   // of those, turns it was missed
  gaps: number;     // turns with no reading
  lowest: number | null;
}

export interface RunSummary {
  turns: number;
  /** The drift at which this contract's first response step starts; null if the contract can't be read. */
  gate: number | null;
  /** Turns with drift at or above the gate (null when the gate is unknown). */
  atOrAbove: number | null;
  firstCorrection: number | null;
  /** The first turn after the first correction on which drift was back below the gate. */
  recoveredAt: number | null;
  gapTurns: number;
  rules: RuleTally[];
}

/** What was detected across a whole run, from its trace: which rules were missed and how often, and the arc of drift. */
export function summarizeRun(states: readonly StateRecord[], info: ContractInfo): RunSummary {
  const gate = responseGate(info);
  const tallies = new Map<string, RuleTally>();
  let gapTurns = 0;

  for (const s of states) {
    if (s.sensor_gaps.length > 0) gapTurns += 1;
    for (const row of detectionRows(s, info)) {
      const t = tallies.get(row.id) ?? { id: row.id, kind: row.kind, scored: 0, missed: 0, gaps: 0, lowest: null };
      if (row.status === "no-reading") t.gaps += 1;
      if (row.status === "met" || row.status === "missed") t.scored += 1;
      if (row.status === "missed") t.missed += 1;
      if (row.reading !== null && (t.lowest === null || row.reading < t.lowest)) t.lowest = row.reading;
      tallies.set(row.id, t);
    }
  }

  const firstIdx = states.findIndex((s) => s.recovery_fired !== null);
  const firstCorrection = firstIdx >= 0 ? states[firstIdx]!.turn : null;
  let recoveredAt: number | null = null;
  if (firstIdx >= 0 && gate !== null) {
    const back = states.slice(firstIdx + 1).find((s) => s.drift < gate);
    recoveredAt = back ? back.turn : null;
  }

  return {
    turns: states.length,
    gate,
    atOrAbove: gate === null ? null : states.filter((s) => s.drift >= gate).length,
    firstCorrection,
    recoveredAt,
    gapTurns,
    rules: [...tallies.values()].sort((a, b) => b.missed - a.missed || a.id.localeCompare(b.id)),
  };
}
