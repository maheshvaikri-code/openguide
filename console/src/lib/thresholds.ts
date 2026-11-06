import type { Json } from "./types";

export interface Thresholds {
  /** Drift at which the contract's first recovery action fires, or null if the contract doesn't say. */
  threshold: number | null;
  /** Drift at which the contract halts the run, or null if it has no halt rung. */
  halt: number | null;
}

export const UNKNOWN_THRESHOLDS: Thresholds = { threshold: null, halt: null };

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/**
 * Read a contract's recovery gates from its stored JSON: `recovery.drift_threshold` and the
 * `halt@x` rung of `recovery.actions`. Never guesses: anything missing is null, and callers
 * must then omit the threshold rather than draw a made-up one. The reconciler fires an action
 * when drift >= its gate (guidancegrid/compiler/compile.py), so "at or above" is the right test.
 */
export function parseThresholds(contract: Json | null | undefined): Thresholds {
  if (!contract || typeof contract !== "object" || Array.isArray(contract)) return UNKNOWN_THRESHOLDS;
  const rec = contract["recovery"];
  if (!rec || typeof rec !== "object" || Array.isArray(rec)) return UNKNOWN_THRESHOLDS;
  let halt: number | null = null;
  const actions = rec["actions"];
  if (Array.isArray(actions)) {
    for (const a of actions) {
      const m = typeof a === "string" ? /^halt@(\d*\.?\d+)$/.exec(a) : null;
      if (m) halt = num(Number(m[1]));
    }
  }
  return { threshold: num(rec["drift_threshold"]), halt };
}

export function atOrAbove(drift: number, gate: number | null): boolean {
  return gate !== null && drift >= gate;
}
