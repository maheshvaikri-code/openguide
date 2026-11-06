import type { StateRecord } from "./types";

export interface Point {
  turn: number;
  x: number;
  y: number;
  z: number;
  drift: number;
  excursion: boolean; // drift above the threshold
  corrected: boolean; // a recovery action fired on this turn
  gap: boolean; // at least one axis was carried forward over a sensor gap
}

export interface Projection {
  axes: [string, string, string];
  points: Point[];
  /** Safe region as [min,max] per axis, in the same 0..1 coordinates as the points. */
  safe: [[number, number], [number, number], [number, number]];
}

const clamp01 = (v: number) => Math.min(Math.max(v, 0), 1);
const DRIFT = "drift";
/** Padding axes are named drift, drift2, ... An invariant that merely starts with "drift" is not one. */
const isDriftAxis = (ax: string) => /^drift\d*$/.test(ax);

/**
 * Choose three axes. Prefer invariants that have a numeric reading and a soft floor
 * (most informative), most-observed first, ties by id; pad with `drift`.
 * Deterministic: same states => same axes.
 */
export function pickAxes(states: readonly StateRecord[]): [string, string, string] {
  const stats = new Map<string, { n: number; floor: boolean }>();
  for (const s of states) {
    for (const [id, inv] of Object.entries(s.invariants)) {
      const cur = stats.get(id) ?? { n: 0, floor: false };
      if (typeof inv.reading === "number") cur.n += 1;
      if (typeof inv.floor === "number" && inv.floor > 0) cur.floor = true;
      stats.set(id, cur);
    }
  }
  const ranked = [...stats.entries()]
    .filter(([, v]) => v.n > 0)
    .sort((a, b) => Number(b[1].floor) - Number(a[1].floor) || b[1].n - a[1].n || a[0].localeCompare(b[0]))
    .map(([id]) => id);
  const axes = ranked.slice(0, 3);
  while (axes.length < 3) axes.push(axes.includes(DRIFT) ? `${DRIFT}${axes.length}` : DRIFT);
  return axes as [string, string, string];
}

/**
 * `threshold` is the contract's drift gate, or null when unknown. With no threshold nothing is
 * flagged as an excursion and the drift axis has no safe band: we don't invent one.
 */
export function project(states: readonly StateRecord[], axes: [string, string, string], threshold: number | null): Projection {
  const last: Record<string, number> = {};
  const points: Point[] = states.map((s) => {
    let gap = false;
    const coord = axes.map((ax) => {
      if (isDriftAxis(ax)) return clamp01(s.drift);
      const r = s.invariants[ax]?.reading;
      if (typeof r === "number") {
        last[ax] = clamp01(r);
        return last[ax]!;
      }
      gap = true;
      return last[ax] ?? 1; // before any reading, assume healthy rather than invent a violation
    });
    return {
      turn: s.turn,
      x: coord[0]!,
      y: coord[1]!,
      z: coord[2]!,
      drift: s.drift,
      excursion: threshold !== null && s.drift >= threshold, // the reconciler fires at drift >= gate
      corrected: s.recovery_fired !== null,
      gap,
    };
  });

  const safeFor = (ax: string): [number, number] => {
    if (isDriftAxis(ax)) return threshold === null ? [0, 1] : [0, clamp01(threshold)];
    for (const s of states) {
      const f = s.invariants[ax]?.floor;
      if (typeof f === "number") return [clamp01(f), 1];
    }
    return [0, 1];
  };
  return { axes, points, safe: [safeFor(axes[0]), safeFor(axes[1]), safeFor(axes[2])] };
}

/** First turn of each contiguous excursion (for "excursion began at turn N"). */
export function excursionStarts(points: readonly Point[]): number[] {
  const out: number[] = [];
  points.forEach((p, i) => {
    if (p.excursion && !points[i - 1]?.excursion) out.push(p.turn);
  });
  return out;
}
