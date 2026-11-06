export interface GridLayout {
  cols: number;
  rows: number;
  cell: number;
  gap: number;
  height: number;
}

export function layoutGrid(count: number, width: number, cell = 8, gap = 2): GridLayout {
  const step = cell + gap;
  const cols = Math.max(1, Math.floor((width + gap) / step));
  const rows = Math.max(1, Math.ceil(count / cols));
  return { cols, rows, cell, gap, height: rows * step - gap };
}

/** Index of the cell under (x, y), or -1 if in a gap, off-grid, or past the last cell. */
export function cellAt(layout: GridLayout, count: number, x: number, y: number): number {
  const step = layout.cell + layout.gap;
  if (x < 0 || y < 0) return -1;
  const col = Math.floor(x / step);
  const row = Math.floor(y / step);
  if (col >= layout.cols || x - col * step >= layout.cell || y - row * step >= layout.cell) return -1;
  const i = row * layout.cols + col;
  return i < count ? i : -1;
}

export type DriftBand = "healthy" | "watch" | "high" | "halt";

/**
 * A fixed descriptive scale for peak drift (0..1). It is NOT any contract's threshold: each
 * contract sets its own (see lib/thresholds.ts). Use it only where no single contract applies,
 * such as a fleet that mixes contracts.
 */
export function driftBand(d: number): DriftBand {
  if (d >= 0.6) return "halt";
  if (d >= 0.3) return "high";
  if (d >= 0.1) return "watch";
  return "healthy";
}

export const BAND_LABEL: Record<DriftBand, string> = {
  healthy: "Low drift",
  watch: "Some drift",
  high: "High drift",
  halt: "Severe drift",
};

/** A text glyph per band so status is never conveyed by colour alone. */
export const BAND_GLYPH: Record<DriftBand, string> = { healthy: "●", watch: "◐", high: "▲", halt: "■" };

const STOPS: Array<[number, [number, number, number]]> = [
  [0.0, [38, 70, 78]],
  [0.1, [70, 160, 150]],
  [0.27, [232, 163, 61]],
  [0.6, [255, 107, 94]],
  [1.0, [255, 150, 140]],
];

/** Continuous colour for a drift value in [0,1] (teal -> amber -> red). */
export function driftColor(d: number): string {
  const v = Math.min(Math.max(Number.isFinite(d) ? d : 0, 0), 1);
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i]!;
    const [t0, c0] = STOPS[i - 1]!;
    if (v <= t1) {
      const f = (v - t0) / (t1 - t0);
      const m = (k: 0 | 1 | 2) => Math.round(c0[k] + (c1[k] - c0[k]) * f);
      return `rgb(${m(0)},${m(1)},${m(2)})`;
    }
  }
  const last = STOPS[STOPS.length - 1]![1];
  return `rgb(${last[0]},${last[1]},${last[2]})`;
}
