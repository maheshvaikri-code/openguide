import { useEffect, useMemo, useRef, useState } from "react";
import { cellAt, driftColor, layoutGrid } from "../lib/heat";
import type { Run } from "../lib/types";

/**
 * One cell per run, coloured by max drift. Drawn on a canvas so 10 000 runs stay cheap.
 * Halted runs carry a dot and unverified traces a red frame, so state isn't colour-only.
 * Keyboard: focus the field, arrows move between runs, Enter opens the selected run.
 */
export function HeatField({
  runs,
  selected,
  newIds,
  onSelect,
  onOpen,
}: {
  runs: readonly Run[];
  selected: number;
  newIds?: ReadonlySet<string>;
  onSelect: (i: number) => void;
  onOpen: (i: number) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(240, Math.floor(el.clientWidth)));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => layoutGrid(runs.length, width), [runs.length, width]);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const ctx = c.getContext?.("2d");
    if (!ctx) return; // no canvas (tests): the table below carries the same information
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.floor(width * dpr);
    c.height = Math.floor(layout.height * dpr);
    c.style.height = `${layout.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, layout.height);
    const step = layout.cell + layout.gap;
    runs.forEach((r, i) => {
      const x = (i % layout.cols) * step;
      const y = Math.floor(i / layout.cols) * step;
      ctx.fillStyle = driftColor(r.max_drift);
      ctx.fillRect(x, y, layout.cell, layout.cell);
      if (r.halted) {
        ctx.fillStyle = "#101318";
        ctx.fillRect(x + layout.cell / 2 - 1.5, y + layout.cell / 2 - 1.5, 3, 3);
      }
      if (!r.verified) {
        ctx.strokeStyle = "#ff6b5e";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x - 0.75, y - 0.75, layout.cell + 1.5, layout.cell + 1.5);
      }
      if (newIds?.has(r.run_id)) {
        ctx.strokeStyle = "#46c8d2";
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x - 1, y - 1, layout.cell + 2, layout.cell + 2);
      }
    });
    if (selected >= 0 && selected < runs.length) {
      const x = (selected % layout.cols) * step;
      const y = Math.floor(selected / layout.cols) * step;
      ctx.strokeStyle = "#eef2f6";
      ctx.lineWidth = 2;
      ctx.strokeRect(x - 2, y - 2, layout.cell + 4, layout.cell + 4);
    }
  }, [runs, layout, width, selected, newIds]);

  const at = (e: React.PointerEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    return { x, y, i: cellAt(layout, runs.length, x, y) };
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (!runs.length) return;
    const cur = selected < 0 ? 0 : selected;
    const move: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: layout.cols, ArrowUp: -layout.cols };
    if (e.key in move) {
      e.preventDefault();
      onSelect(Math.min(Math.max(cur + move[e.key]!, 0), runs.length - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      onSelect(0);
    } else if (e.key === "End") {
      e.preventDefault();
      onSelect(runs.length - 1);
    } else if (e.key === "Enter" && selected >= 0) {
      e.preventDefault();
      onOpen(selected);
    }
  };

  const sel = selected >= 0 ? runs[selected] : undefined;
  const tip = hover && runs[hover.i];

  return (
    <div className="field-wrap" ref={wrap}>
      <canvas
        ref={canvas}
        tabIndex={0}
        role="application"
        aria-label={`Run field with ${runs.length} runs, each cell coloured by peak drift. Use arrow keys to move between runs and Enter to open the selected run.`}
        onKeyDown={onKey}
        onFocus={() => selected < 0 && runs.length && onSelect(0)}
        onPointerMove={(e) => {
          const p = at(e);
          setHover(p.i >= 0 ? p : null);
        }}
        onPointerLeave={() => setHover(null)}
        onClick={(e) => {
          const p = at(e as unknown as React.PointerEvent);
          if (p.i >= 0) onSelect(p.i);
        }}
        onDoubleClick={(e) => {
          const p = at(e as unknown as React.PointerEvent);
          if (p.i >= 0) onOpen(p.i);
        }}
      />
      <div className="sr-only" aria-live="polite">
        {sel ? `${sel.run_id}, peak drift ${sel.max_drift.toFixed(2)}${sel.halted ? ", halted" : ""}` : ""}
      </div>
      {tip && hover && (
        <div className="tip" style={{ left: Math.min(hover.x + 22, width - 250), top: hover.y + 28 }}>
          <b className="mono">{tip.run_id}</b>
          <br />
          <span className="num">peak drift {tip.max_drift.toFixed(2)}</span>
          {" · "}
          {tip.recoveries} {tip.recoveries === 1 ? "correction" : "corrections"}
          {" · "}
          {tip.turns} turns
          <br />
          <span className="muted">{tip.model}</span>
          {tip.halted ? " · halted" : ""}
          {!tip.verified && tip.trace_cas_key ? " · trace chain broken" : ""}
        </div>
      )}
    </div>
  );
}
