import { BAND_GLYPH, BAND_LABEL, driftBand, driftColor } from "../lib/heat";

/** "sha256:026d89e9…" -> "026d89e9" */
export function shortHash(h: string | null | undefined, n = 8): string {
  if (!h) return "none";
  return h.replace(/^sha256:/, "").slice(0, n);
}

export function fmt(n: number | null | undefined, digits = 2): string {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(digits) : "no reading";
}

/** Status is always glyph + text, never colour alone. */
export function BandBadge({ drift }: { drift: number }) {
  const band = driftBand(drift);
  return (
    <span className="badge" style={{ color: driftColor(Math.max(drift, band === "healthy" ? 0.12 : drift)) }}>
      <span aria-hidden="true">{BAND_GLYPH[band]}</span>
      {BAND_LABEL[band]}
    </span>
  );
}

/**
 * `stored` is whether a full trace is kept. The fleet index carries a `verified` flag written by
 * whoever indexed the run; without a stored trace nothing can be re-checked here, so say that
 * instead of repeating the flag as if it had been verified.
 */
export function VerifiedBadge({ ok, stored = true }: { ok: boolean; stored?: boolean }) {
  if (!stored) {
    return <span className="badge" title="The fleet index has no stored trace for this run, so its chain can't be re-checked here."><span aria-hidden="true">○</span>Not re-checked</span>;
  }
  return ok ? (
    <span className="badge ok"><span aria-hidden="true">✓</span>Chain verified</span>
  ) : (
    <span className="badge bad"><span aria-hidden="true">✕</span>Chain broken</span>
  );
}
