import React, { useState, useMemo, useRef, useEffect, useCallback } from "react";

// ─── GuidanceGrid · Replay Console ───────────────────────────────────
// Step-by-step playback of a gridded agent run: the (layer × step)
// spectrogram reveals as the playhead sweeps, the generated text
// streams on the side annotated by the dominant live signal, a layer
// meter shows where in the network injection is happening right now,
// and a trace log prints every grid event as a literal.

const STEPS = 100;
const COLS = 50;
const LAYERS = 32;
const PHASES = [
  { name: "PLAN", from: 0, to: 20 },
  { name: "ACT", from: 20, to: 80 },
  { name: "REFLECT", from: 80, to: 100 },
];
const TOOL_EVENTS = [30, 60];

const SIG = {
  anchor:    { label: "ANCHOR",    hex: "#e8a33d", rgb: [232,163,61],  layers: [12,24], curve: "ramp 0→g over ctx" },
  precision: { label: "PRECISION", hex: "#46c8d2", rgb: [70,200,210],  layers: [20,30], curve: "spike@tool · τ=8" },
  explore:   { label: "EXPLORE",   hex: "#9b7bf0", rgb: [155,123,240], layers: [8,16],  curve: "window 0–20" },
  damp:      { label: "SYC-DAMP",  hex: "#e06a8a", rgb: [224,106,138], layers: [14,22], curve: "const g" },
};

function gainAt(key, g, t) {
  if (g <= 0) return 0;
  if (key === "anchor") return g * (0.15 + 0.85 * Math.pow(t / STEPS, 0.9));
  if (key === "precision") {
    let v = 0;
    for (const e of TOOL_EVENTS) if (t >= e) v = Math.max(v, g * Math.exp(-(t - e) / 8));
    return v;
  }
  if (key === "explore") {
    const rise = 1 / (1 + Math.exp(-(t - 2) / 1.5));
    const fall = 1 / (1 + Math.exp((t - 19) / 2));
    return g * rise * fall;
  }
  if (key === "damp") return g * 0.85;
  return 0;
}
function layerEnv(key, layer) {
  const [lo, hi] = SIG[key].layers;
  const c = (lo + hi) / 2, w = (hi - lo) / 2.2;
  return Math.exp(-Math.pow((layer - c) / w, 2));
}

// ── simulated transcript: one agent run, words mapped to steps ──
const SEGMENTS = [
  { from: 0,  to: 4,   kind: "plan",    text: "Task received: refactor the config loader for typed validation." },
  { from: 5,  to: 12,  kind: "plan",    text: "Constraints: preserve backward compatibility, no new dependencies, keep the public API stable." },
  { from: 13, to: 20,  kind: "plan",    text: "Plan: parse existing schema, isolate IO boundary, add validation pass, patch tests." },
  { from: 21, to: 29,  kind: "gen",     text: "Beginning implementation. Opening the loader module to map current structure before any edit." },
  { from: 30, to: 33,  kind: "tool",    text: "⟨tool:read_file path=src/config.rs⟩" },
  { from: 34, to: 38,  kind: "result",  text: "[647 lines · 3 structs · serde untyped map]" },
  { from: 39, to: 59,  kind: "gen",     text: "Replacing the untyped map with a ConfigSchema struct, deriving Deserialize, routing env overrides through a single resolve() with explicit precedence order, and attaching key paths to every error variant." },
  { from: 60, to: 63,  kind: "tool",    text: "⟨tool:run_tests scope=config⟩" },
  { from: 64, to: 67,  kind: "result",  text: "[42 passed · 0 failed · 1.8s]" },
  { from: 68, to: 79,  kind: "gen",     text: "Tests green. Adding two regression cases for missing-key and override-precedence, then tightening the doc comments." },
  { from: 80, to: 100, kind: "reflect", text: "Verification pass: the original instruction required backward compatibility — public API unchanged, serialized format identical, all 14 call sites compile. Constraint held end to end. Done." },
];

function buildTokens() {
  const tokens = Array.from({ length: STEPS + 1 }, () => null);
  for (const seg of SEGMENTS) {
    const words = seg.text.split(" ");
    const span = seg.to - seg.from + 1;
    for (let i = 0; i < span; i++) {
      const wFrom = Math.floor((i * words.length) / span);
      const wTo = Math.floor(((i + 1) * words.length) / span);
      const chunk = words.slice(wFrom, wTo).join(" ");
      tokens[seg.from + i] = { text: chunk, kind: seg.kind };
    }
  }
  return tokens;
}
const TOKENS = buildTokens();
const KIND_COLOR = { plan: "#9b7bf0", gen: "#c9d1d9", tool: "#46c8d2", result: "#7ddb8a", reflect: "#e8a33d" };

export default function GuidanceGridReplay() {
  const [gains, setGains] = useState({ anchor: 0.55, precision: 0.7, explore: 0.5, damp: 0.3 });
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const streamRef = useRef(null);
  const logRef = useRef(null);
  const gridRef = useRef(null);

  // ── simulation ──
  const sim = useMemo(() => {
    const g = {}, total = new Array(STEPS + 1).fill(0);
    for (const k of Object.keys(SIG)) {
      g[k] = [];
      for (let t = 0; t <= STEPS; t++) { g[k][t] = gainAt(k, gains[k], t); total[t] += g[k][t]; }
    }
    const baseline = [], gridded = [];
    const meanTotal = total.reduce((a, b) => a + b, 0) / (STEPS + 1);
    const cap = Math.max(0, 1 - 0.16 * Math.pow(meanTotal, 1.5));
    for (let t = 0; t <= STEPS; t++) {
      const wig = 0.018 * Math.sin(t / 5.3) + 0.012 * Math.sin(t / 2.1 + 1.7);
      baseline[t] = 0.92 - 0.5 * Math.pow(t / STEPS, 1.25) + wig;
      gridded[t] = Math.min(0.975, baseline[t] + 0.62 * g.anchor[t] + 0.06 * g.damp[t]) * (0.55 + 0.45 * cap);
    }
    return { g, total, baseline, gridded };
  }, [gains]);

  // ── trace log events (the literals) ──
  const events = useMemo(() => {
    const ev = [];
    ev.push({ t: 0, kind: "phase", text: "ENTER PLAN · EXPLORE window opens L8–16" });
    if (gains.damp > 0) ev.push({ t: 0, kind: "sig", hex: SIG.damp.hex, text: `SYC-DAMP const ${(gains.damp * 0.85).toFixed(2)} · L14–22` });
    let c25 = false, c50 = false;
    for (let t = 0; t <= STEPS; t++) {
      const a = sim.g.anchor[t];
      if (!c25 && a >= 0.25) { c25 = true; ev.push({ t, kind: "sig", hex: SIG.anchor.hex, text: `ANCHOR crosses 0.25 · ramp engaged L12–24` }); }
      if (!c50 && a >= 0.5)  { c50 = true; ev.push({ t, kind: "sig", hex: SIG.anchor.hex, text: `ANCHOR crosses 0.50 · drift compensation dominant` }); }
      if (sim.total[t] > 1.25 && !(ev.some(e => e.kind === "warn"))) ev.push({ t, kind: "warn", text: `Σgain ${sim.total[t].toFixed(2)} > 1.25 · norm-preserving projection applied` });
    }
    ev.push({ t: 19, kind: "phase", text: "EXPLORE window closing · plan committed" });
    ev.push({ t: 20, kind: "phase", text: "ENTER ACT" });
    for (const e of TOOL_EVENTS) {
      ev.push({ t: e, kind: "trig", hex: SIG.precision.hex, text: `TRIGGER token:⟨tool⟩ → PRECISION ${gains.precision.toFixed(2)} inject L20–30` });
      ev.push({ t: e + 8, kind: "sig", hex: SIG.precision.hex, text: `PRECISION decayed to ${(gains.precision * Math.exp(-1)).toFixed(2)} (τ=8)` });
    }
    ev.push({ t: 80, kind: "phase", text: "ENTER REFLECT · ANCHOR at peak hold" });
    ev.push({ t: 100, kind: "phase", text: `RUN END · adherence ${(sim.gridded[100] * 100).toFixed(0)}% vs baseline ${(sim.baseline[100] * 100).toFixed(0)}% · trace hash a3f2…9c (replayable)` });
    return ev.sort((a, b) => a.t - b.t);
  }, [sim, gains]);

  // ── grid cells ──
  const cells = useMemo(() => {
    const out = [];
    for (let li = 0; li < LAYERS; li++)
      for (let c = 0; c < COLS; c++) {
        const t = Math.round((c / (COLS - 1)) * STEPS);
        let r = 0, gg = 0, b = 0, mag = 0;
        for (const k of Object.keys(SIG)) {
          const v = sim.g[k][t] * layerEnv(k, li);
          if (v > 0.01) { const [cr, cg, cb] = SIG[k].rgb; r += cr * v; gg += cg * v; b += cb * v; mag += v; }
        }
        if (mag > 0.02)
          out.push({ li, c, t, fill: `rgb(${Math.min(255, r) | 0},${Math.min(255, gg) | 0},${Math.min(255, b) | 0})`, a: Math.min(1, mag * 1.15) });
      }
    return out;
  }, [sim]);

  // ── playback loop ──
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setStep((s) => {
        if (s >= STEPS) { setPlaying(false); return s; }
        return s + 1;
      });
    }, 220 / speed);
    return () => clearInterval(id);
  }, [playing, speed]);

  // auto-scroll panels
  useEffect(() => {
    if (streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight;
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [step]);

  const onGridPointer = useCallback((e) => {
    const svg = gridRef.current; if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    setStep(Math.max(0, Math.min(STEPS, Math.round(x * STEPS))));
    setPlaying(false);
  }, []);

  const dominantAt = (t) => {
    let best = null, bv = 0.04;
    for (const k of Object.keys(SIG)) if (sim.g[k][t] > bv) { bv = sim.g[k][t]; best = k; }
    return best;
  };

  // geometry
  const GW = 1000, GH = 340, cw = GW / COLS, ch = GH / LAYERS;
  const ix = (step / STEPS) * GW;
  const phase = PHASES.find((p) => step >= p.from && step <= p.to) || PHASES[2];

  // layer meter at current step
  const meter = [];
  for (let li = 0; li < LAYERS; li++) {
    let r = 0, gg = 0, b = 0, mag = 0;
    for (const k of Object.keys(SIG)) {
      const v = sim.g[k][step] * layerEnv(k, li);
      if (v > 0.01) { const [cr, cg, cb] = SIG[k].rgb; r += cr * v; gg += cg * v; b += cb * v; mag += v; }
    }
    meter.push({ mag: Math.min(1, mag), fill: mag > 0.02 ? `rgb(${Math.min(255, r) | 0},${Math.min(255, gg) | 0},${Math.min(255, b) | 0})` : "#1c222b" });
  }

  const btn = { fontFamily: "inherit", fontSize: 12, background: "#161b22", color: "#c9d1d9", border: "1px solid #3a4250", borderRadius: 4, padding: "5px 12px", cursor: "pointer" };

  return (
    <div style={{ background: "#101318", minHeight: "100vh", color: "#c9d1d9", fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
        input[type=range]{ -webkit-appearance:none; appearance:none; height:3px; border-radius:2px; outline:none; }
        input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; appearance:none; width:14px; height:14px; border-radius:50%; background:#c9d1d9; border:2px solid #101318; cursor:pointer; }
        @media (prefers-reduced-motion: reduce){ *{ transition:none !important; animation:none !important; } }
      `}</style>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "20px 14px 48px" }}>
        {/* header */}
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", gap: 8, borderBottom: "1px solid #2a313c", paddingBottom: 12 }}>
          <div>
            <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, fontSize: 24, letterSpacing: "0.04em", color: "#eef2f6" }}>
              GUIDANCE<span style={{ color: "#e8a33d" }}>GRID</span> <span style={{ fontWeight: 500, fontSize: 15, color: "#6b7684" }}>· REPLAY</span>
            </div>
            <div style={{ fontSize: 11, color: "#6b7684", marginTop: 2 }}>trace playback · run #0042 · "refactor config loader" · 32L / 100 steps</div>
          </div>
          <div style={{ fontSize: 11, color: "#6b7684" }}>every token logs its live signals — the run is a replayable artifact</div>
        </div>

        {/* transport */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          <button style={{ ...btn, background: playing ? "#e8a33d" : "#161b22", color: playing ? "#101318" : "#c9d1d9", fontWeight: 600, minWidth: 72 }}
            onClick={() => { if (step >= STEPS) setStep(0); setPlaying((p) => !p); }}>
            {playing ? "⏸ PAUSE" : step >= STEPS ? "↺ REPLAY" : "▶ PLAY"}
          </button>
          <button style={btn} onClick={() => { setPlaying(false); setStep(0); }}>⏮</button>
          <button style={btn} onClick={() => { setPlaying(false); setStep((s) => Math.min(STEPS, s + 1)); }}>+1</button>
          <select value={speed} onChange={(e) => setSpeed(parseFloat(e.target.value))} style={{ ...btn, padding: "5px 8px" }}>
            <option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={4}>4×</option>
          </select>
          <input type="range" min={0} max={STEPS} value={step} onChange={(e) => { setPlaying(false); setStep(parseInt(e.target.value)); }}
            style={{ flex: 1, minWidth: 140, background: `linear-gradient(to right, #e8a33d ${step}%, #2a313c ${step}%)` }} />
          <span style={{ fontSize: 13, width: 110, textAlign: "right" }}>
            t=<b style={{ color: "#eef2f6" }}>{String(step).padStart(3, "0")}</b>/{STEPS} · <span style={{ color: "#9b7bf0" }}>{phase.name}</span>
          </span>
        </div>

        {/* grid + layer meter */}
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <div style={{ flex: 1, minWidth: 0, background: "#0b0e12", border: "1px solid #2a313c", borderRadius: 6, padding: 8 }}>
            <svg ref={gridRef} viewBox={`0 0 ${GW} ${GH}`} style={{ width: "100%", display: "block", touchAction: "none", cursor: "crosshair" }}
              onPointerDown={onGridPointer} onPointerMove={(e) => e.buttons > 0 && onGridPointer(e)}>
              <rect width={GW} height={GH} fill="#0b0e12" />
              {[8, 16, 24].map((l) => (
                <line key={l} x1={0} x2={GW} y1={GH - (l / LAYERS) * GH} y2={GH - (l / LAYERS) * GH} stroke="#1c222b" />
              ))}
              {cells.map((c, i) => (
                <rect key={i} x={c.c * cw} y={GH - (c.li + 1) * ch} width={cw + 0.5} height={ch + 0.5}
                  fill={c.fill} opacity={c.t <= step ? c.a : c.a * 0.13} />
              ))}
              {TOOL_EVENTS.map((e) => (
                <line key={e} x1={(e / STEPS) * GW} x2={(e / STEPS) * GW} y1={0} y2={GH} stroke="#46c8d2" strokeWidth={1} strokeDasharray="2 6" opacity={e <= step ? 0.6 : 0.2} />
              ))}
              <line x1={ix} x2={ix} y1={0} y2={GH} stroke="#eef2f6" strokeWidth={1.5} />
              <rect x={ix - 1.5} y={0} width={3} height={10} fill="#eef2f6" />
            </svg>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#6b7684", marginTop: 4 }}>
              <span>L0 → L31 · past revealed, future dimmed</span><span>drag to scrub</span>
            </div>
          </div>
          {/* layer meter */}
          <div style={{ width: 56, background: "#0b0e12", border: "1px solid #2a313c", borderRadius: 6, padding: 8, display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 9, color: "#6b7684", textAlign: "center", marginBottom: 4 }}>INJECT<br />@t</div>
            <svg viewBox={`0 0 40 ${GH}`} style={{ width: "100%", flex: 1 }}>
              {meter.map((m, li) => (
                <rect key={li} x={0} y={GH - (li + 1) * ch + 0.5} width={Math.max(2, m.mag * 40)} height={ch - 1} fill={m.fill} />
              ))}
            </svg>
          </div>
        </div>

        {/* live signal readout */}
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 10, fontSize: 11, alignItems: "center" }}>
          {Object.entries(SIG).map(([k, d]) => {
            const v = sim.g[k][step];
            return (
              <span key={k} style={{ color: v > 0.02 ? d.hex : "#3a4250" }}>
                {v > 0.02 ? "●" : "○"} {d.label} {v.toFixed(2)}
              </span>
            );
          })}
          <span style={{ color: sim.total[step] > 1.25 ? "#ff6b5e" : "#6b7684" }}>Σ {sim.total[step].toFixed(2)}</span>
          <span style={{ color: "#7ddb8a" }}>adherence {(sim.gridded[step] * 100).toFixed(0)}%</span>
          <span style={{ color: "#ff6b5e" }}>baseline {(sim.baseline[step] * 100).toFixed(0)}%</span>
        </div>

        {/* stream + trace log */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(290px, 1fr))", gap: 12, marginTop: 16 }}>
          {/* token stream */}
          <div style={{ background: "#0b0e12", border: "1px solid #2a313c", borderRadius: 6, display: "flex", flexDirection: "column", minWidth: 0 }}>
            <div style={{ fontSize: 10, color: "#6b7684", padding: "8px 12px", borderBottom: "1px solid #1c222b" }}>
              GENERATED STREAM · underline = dominant live signal ·
              <span style={{ color: "#9b7bf0" }}> plan</span> <span style={{ color: "#46c8d2" }}>tool</span> <span style={{ color: "#7ddb8a" }}>result</span> <span style={{ color: "#e8a33d" }}>reflect</span>
            </div>
            <div ref={streamRef} style={{ padding: "10px 12px", height: 240, overflowY: "auto", fontSize: 13, lineHeight: 2.1 }}>
              {TOKENS.map((tok, t) => {
                if (!tok || !tok.text || t > step) return null;
                const dom = dominantAt(t);
                return (
                  <span key={t}
                    title={`t=${t}`}
                    style={{
                      color: KIND_COLOR[tok.kind],
                      background: t === step ? "#eef2f622" : "transparent",
                      borderBottom: dom ? `2px solid ${SIG[dom].hex}` : "2px solid transparent",
                      paddingBottom: 1, marginRight: 5, whiteSpace: "pre-wrap",
                    }}>
                    {tok.text}
                  </span>
                );
              })}
              {step < STEPS && <span style={{ color: "#eef2f6" }}>▌</span>}
            </div>
          </div>

          {/* trace log */}
          <div style={{ background: "#0b0e12", border: "1px solid #2a313c", borderRadius: 6, display: "flex", flexDirection: "column", minWidth: 0 }}>
            <div style={{ fontSize: 10, color: "#6b7684", padding: "8px 12px", borderBottom: "1px solid #1c222b" }}>GRID TRACE · literal event log</div>
            <div ref={logRef} style={{ padding: "10px 12px", height: 240, overflowY: "auto", fontSize: 11, lineHeight: 1.9 }}>
              {events.filter((e) => e.t <= step).map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 8 }}>
                  <span style={{ color: "#4a5260", flexShrink: 0 }}>t={String(e.t).padStart(3, "0")}</span>
                  <span style={{
                    color: e.kind === "warn" ? "#ff6b5e" : e.kind === "phase" ? "#8a94a3" : e.hex || "#c9d1d9",
                    fontWeight: e.kind === "trig" ? 600 : 400,
                  }}>
                    {e.kind === "trig" ? "⚡ " : e.kind === "warn" ? "⚠ " : e.kind === "phase" ? "── " : "· "}{e.text}
                  </span>
                </div>
              ))}
              {step === 0 && <div style={{ color: "#4a5260" }}>press ▶ PLAY to start the trace…</div>}
            </div>
          </div>
        </div>

        {/* compact faders */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, marginTop: 16 }}>
          {Object.entries(SIG).map(([k, d]) => (
            <div key={k} style={{ background: "#161b22", border: "1px solid #2a313c", borderRadius: 6, padding: "8px 12px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10 }}>
                <span style={{ color: d.hex, fontWeight: 600, letterSpacing: "0.06em" }}>{d.label}</span>
                <span style={{ color: "#6b7684" }}>L{d.layers[0]}–{d.layers[1]} · {d.curve}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                <input type="range" min={0} max={1} step={0.01} value={gains[k]}
                  onChange={(e) => setGains((s) => ({ ...s, [k]: parseFloat(e.target.value) }))}
                  style={{ flex: 1, background: `linear-gradient(to right, ${d.hex} ${gains[k] * 100}%, #2a313c ${gains[k] * 100}%)` }} />
                <span style={{ fontSize: 11, width: 30, textAlign: "right" }}>{gains[k].toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 16, fontSize: 10, color: "#4a5260", lineHeight: 1.6, borderTop: "1px solid #2a313c", paddingTop: 10 }}>
          simulated trace — transcript and dynamics are illustrative. in the real runtime this view renders from the recorded per-token signal log:
          (step, layer-range, signal, gain, Σ, norm-correction) tuples — hash-chained, so any run replays bit-identically from its trace.
        </div>
      </div>
    </div>
  );
}
