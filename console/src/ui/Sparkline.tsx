/** Small line chart over turns. Null values break the line (sensor gaps are shown, not hidden). */
export function Sparkline({
  values,
  floor,
  color = "var(--cyan)",
  marks = [],
  at,
  label,
}: {
  values: ReadonlyArray<number | null>;
  floor?: number | null;
  color?: string;
  marks?: number[];
  at?: number;
  label: string;
}) {
  const W = 300;
  const H = 44;
  const n = Math.max(values.length - 1, 1);
  const x = (i: number) => (i / n) * W;
  const y = (v: number) => H - 3 - Math.min(Math.max(v, 0), 1) * (H - 6);
  const segs: string[] = [];
  let cur: string[] = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (cur.length) segs.push(cur.join(" "));
      cur = [];
    } else {
      cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    }
  });
  if (cur.length) segs.push(cur.join(" "));
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label}>
      {typeof floor === "number" && (
        <line x1="0" x2={W} y1={y(floor)} y2={y(floor)} stroke="var(--muted)" strokeDasharray="3 3" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      )}
      {segs.map((p, i) => (
        <polyline key={i} points={p} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      ))}
      {marks.map((m) => (
        <line key={m} x1={x(m)} x2={x(m)} y1="0" y2={H} stroke="var(--cyan)" strokeWidth="1" opacity="0.55" vectorEffect="non-scaling-stroke" />
      ))}
      {typeof at === "number" && (
        <line x1={x(at)} x2={x(at)} y1="0" y2={H} stroke="var(--strong)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      )}
    </svg>
  );
}
