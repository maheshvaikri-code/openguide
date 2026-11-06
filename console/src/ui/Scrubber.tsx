import { useMemo, useRef } from "react";
import { BAND_LABEL, driftBand } from "../lib/heat";
import { clampIndex, correctionIndexes } from "../lib/replay";
import type { StateRecord } from "../lib/types";

const W = 960;
const H = 230;
const PAD = { l: 38, r: 14, t: 14, b: 30 };

/**
 * The replay timeline: drift over turns, the contract threshold, every correction, and a
 * draggable playhead. The optional baseline (an ungoverned run) is drawn behind the run.
 * It is a slider for assistive tech: arrow keys step one turn, Page keys ten.
 */
export function Scrubber({
  states,
  baseline,
  threshold,
  index,
  onIndex,
}: {
  states: readonly StateRecord[];
  baseline?: readonly StateRecord[];
  /** The run's contract drift gate, or null if unknown (then no line is drawn: we don't guess). */
  threshold: number | null;
  index: number;
  onIndex: (i: number) => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const n = Math.max(states.length - 1, 1);
  const top = Math.max(0.8, ...states.map((s) => s.drift), ...(baseline ?? []).map((s) => s.drift));
  const x = (i: number) => PAD.l + (i / n) * (W - PAD.l - PAD.r);
  const y = (d: number) => PAD.t + (1 - Math.min(d / top, 1)) * (H - PAD.t - PAD.b);

  const line = useMemo(() => states.map((s, i) => `${x(i).toFixed(1)},${y(s.drift).toFixed(1)}`).join(" "), [states, top]); // eslint-disable-line react-hooks/exhaustive-deps
  // Only the turns both runs share are drawn: a longer comparison run is cut at this run's
  // last turn instead of being squashed onto it.
  const base = useMemo(
    () => (baseline ?? []).slice(0, states.length).map((s, i) => `${x(i).toFixed(1)},${y(s.drift).toFixed(1)}`).join(" "),
    [baseline, states.length, top, n], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const corrections = useMemo(() => correctionIndexes(states), [states]);
  const cur = states[clampIndex(index, states.length)];

  const seek = (clientX: number) => {
    const el = svg.current;
    if (!el || !states.length) return;
    const rect = el.getBoundingClientRect();
    const px = ((clientX - rect.left) / rect.width) * W;
    onIndex(clampIndex(((px - PAD.l) / (W - PAD.l - PAD.r)) * n, states.length));
  };

  const onKey = (e: React.KeyboardEvent) => {
    const step: Record<string, number> = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 };
    if (e.key in step) {
      e.preventDefault();
      onIndex(clampIndex(index + step[e.key]!, states.length));
    } else if (e.key === "Home") {
      e.preventDefault();
      onIndex(0);
    } else if (e.key === "End") {
      e.preventDefault();
      onIndex(states.length - 1);
    }
  };

  const valueText = cur
    ? `Turn ${cur.turn}, drift ${cur.drift.toFixed(2)}, ${BAND_LABEL[driftBand(cur.drift)].toLowerCase()}${cur.recovery_fired ? `, ${cur.recovery_fired} fired` : ""}`
    : "No turns";

  return (
    <div className="scrub">
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        tabIndex={0}
        role="slider"
        aria-label="Replay position"
        aria-valuemin={0}
        aria-valuemax={Math.max(states.length - 1, 0)}
        aria-valuenow={clampIndex(index, states.length)}
        aria-valuetext={valueText}
        onKeyDown={onKey}
        onPointerDown={(e) => {
          (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
          seek(e.clientX);
        }}
        onPointerMove={(e) => e.buttons === 1 && seek(e.clientX)}
      >
        {[0, 0.2, 0.4, 0.6, 0.8].filter((g) => g <= top).map((g) => (
          <g key={g}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(g)} y2={y(g)} stroke="var(--rule)" strokeWidth="1" />
            <text x={PAD.l - 8} y={y(g) + 4} textAnchor="end" fontSize="11" fill="var(--muted)" className="num">{g.toFixed(1)}</text>
          </g>
        ))}
        {threshold !== null && (
          <>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(threshold)} y2={y(threshold)} stroke="var(--amber)" strokeDasharray="5 4" strokeWidth="1.2" />
            <text x={W - PAD.r} y={y(threshold) - 5} textAnchor="end" fontSize="11" fill="var(--amber)">contract threshold {threshold}</text>
          </>
        )}

        {baseline && baseline.length > 0 && (
          <polyline points={base} fill="none" stroke="var(--rose)" strokeWidth="1.8" strokeDasharray="2 3" />
        )}
        {states.length > 0 && (
          <>
            <polygon points={`${x(0)},${y(0)} ${line} ${x(states.length - 1)},${y(0)}`} fill="var(--cyan)" opacity="0.13" />
            <polyline points={line} fill="none" stroke="var(--cyan)" strokeWidth="2.2" strokeLinejoin="round" />
          </>
        )}

        {corrections.map((c) => (
          <g key={c}>
            <line x1={x(c)} x2={x(c)} y1={PAD.t} y2={H - PAD.b} stroke="var(--green)" strokeWidth="1" opacity="0.5" />
            <path d={`M${x(c) - 5},${H - PAD.b + 12} L${x(c) + 5},${H - PAD.b + 12} L${x(c)},${H - PAD.b + 3} Z`} fill="var(--green)" />
          </g>
        ))}

        {[0, Math.round(n / 4), Math.round(n / 2), Math.round((3 * n) / 4), n].map((t) => (
          <text key={t} x={x(t)} y={H - 2} textAnchor="middle" fontSize="11" fill="var(--muted)" className="num">{states[t]?.turn ?? t}</text>
        ))}

        {cur && (
          <g>
            <line x1={x(index)} x2={x(index)} y1={PAD.t} y2={H - PAD.b} stroke="var(--strong)" strokeWidth="1.5" />
            <circle cx={x(index)} cy={y(cur.drift)} r="5.5" fill="var(--ink)" stroke="var(--strong)" strokeWidth="2" />
          </g>
        )}
      </svg>
      <div className="legend" style={{ padding: "6px 4px 0" }}>
        <span><span style={{ color: "var(--cyan)" }} aria-hidden="true">━</span> Drift of this run</span>
        {baseline && baseline.length > 0 && <span><span style={{ color: "var(--rose)" }} aria-hidden="true">┅</span> Comparison run</span>}
        <span><span style={{ color: "var(--green)" }} aria-hidden="true">▲</span> Correction fired</span>
        {threshold !== null && <span><span style={{ color: "var(--amber)" }} aria-hidden="true">┅</span> Contract threshold</span>}
      </div>
    </div>
  );
}
