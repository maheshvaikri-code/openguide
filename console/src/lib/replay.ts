import type { StateRecord } from "./types";

export interface ParsedTrace {
  states: StateRecord[];
  ignored: number; // records that weren't well-formed STATE records
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const numOrNull = (v: unknown): number | null => (isNum(v) ? v : null);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

function invariants(v: unknown): StateRecord["invariants"] {
  const out: StateRecord["invariants"] = {};
  if (!v || typeof v !== "object" || Array.isArray(v)) return out;
  for (const [id, raw] of Object.entries(v as Record<string, unknown>)) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const r = raw as Record<string, unknown>;
    out[id] = {
      reading: numOrNull(r["reading"]),
      floor: numOrNull(r["floor"]),
      violated: r["violated"] === true,
      ...(typeof r["determinism"] === "string" ? { determinism: r["determinism"] } : {}),
    };
  }
  return out;
}

function signals(v: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  if (!v || typeof v !== "object" || Array.isArray(v)) return out;
  for (const [k, g] of Object.entries(v as Record<string, unknown>)) if (isNum(g)) out[k] = g;
  return out;
}

/** Keep well-formed STATE records, in turn order. Never throws on odd input. */
export function parseStates(records: ReadonlyArray<Record<string, unknown>> | undefined): ParsedTrace {
  const states: StateRecord[] = [];
  let ignored = 0;
  for (const r of records ?? []) {
    if (r && r["ev"] === "STATE" && isNum(r["turn"]) && isNum(r["drift"])) {
      states.push({
        ev: "STATE",
        turn: r["turn"],
        tier_active: String(r["tier_active"] ?? ""),
        invariants: invariants(r["invariants"]),
        drift: r["drift"],
        signals_active: signals(r["signals_active"]),
        recovery_fired: typeof r["recovery_fired"] === "string" ? r["recovery_fired"] : null,
        validation_failures: strings(r["validation_failures"]),
        sensor_gaps: strings(r["sensor_gaps"]),
        reanchored: r["reanchored"] === true,
      });
    } else {
      ignored += 1;
    }
  }
  states.sort((a, b) => a.turn - b.turn);
  return { states, ignored };
}

/** Index (into states) of the first record where a recovery action fired, or -1. */
export function firstCorrection(states: readonly StateRecord[]): number {
  return states.findIndex((s) => s.recovery_fired !== null);
}

export function correctionIndexes(states: readonly StateRecord[]): number[] {
  const out: number[] = [];
  states.forEach((s, i) => {
    if (s.recovery_fired !== null) out.push(i);
  });
  return out;
}

export function invariantIds(states: readonly StateRecord[]): string[] {
  const seen = new Set<string>();
  for (const s of states) for (const id of Object.keys(s.invariants)) seen.add(id);
  return [...seen].sort();
}

/** Reading per turn for one invariant; null where the sensor had a gap or was absent. */
export function readingSeries(states: readonly StateRecord[], id: string): Array<number | null> {
  return states.map((s) => {
    const v = s.invariants[id]?.reading;
    return isNum(v) ? v : null;
  });
}

export function signalIds(states: readonly StateRecord[]): string[] {
  const seen = new Set<string>();
  for (const s of states) for (const id of Object.keys(s.signals_active)) seen.add(id);
  return [...seen].sort();
}

export function clampIndex(i: number, length: number): number {
  if (length <= 0) return 0;
  return Math.min(Math.max(Math.round(i), 0), length - 1);
}
