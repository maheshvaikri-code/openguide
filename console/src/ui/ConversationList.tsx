import type { ContractInfo } from "../lib/contractInfo";
import type { StateRecord, TurnRecord } from "../lib/types";

const clip = (s: string, n = 90) => {
  const t = s.replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t || "(empty)";
};

/**
 * The ids of rules missed on this turn: soft rules below their floor, plus any failed hard rule. A hard
 * rule is judged by its validation result, not by a floor, so its `violated` flag is ignored.
 */
export function missedRules(s: StateRecord, info?: ContractInfo): string[] {
  const hard = (id: string) => info?.rules[id]?.hard === true;
  return [
    ...Object.entries(s.invariants).filter(([id, v]) => v.violated && !hard(id)).map(([id]) => id),
    ...s.validation_failures.filter((id) => !(s.invariants[id]?.violated && !hard(id))),
  ];
}

/** Every turn at a glance: who said what, whether the rules held, and what the contract did about it. */
export function ConversationList({
  states,
  turns,
  index,
  info,
  onPick,
}: {
  states: readonly StateRecord[];
  turns: ReadonlyMap<number, TurnRecord>;
  index: number;
  info?: ContractInfo;
  onPick: (i: number) => void;
}) {
  return (
    <section className="panel" aria-label="Every turn">
      <header>
        <h2>Every turn</h2>
        <span className="muted">Select a turn to see the full text and what was detected.</span>
      </header>
      <div className="events">
        <table>
          <thead>
            <tr>
              <th className="r">Turn</th>
              {turns.size > 0 && <><th>User asked</th><th>Model replied</th></>}
              <th>Rules</th><th className="r">Drift</th><th>Contract</th>
            </tr>
          </thead>
          <tbody>
            {states.map((s, i) => {
              const t = turns.get(s.turn);
              const missed = missedRules(s, info);
              return (
                <tr key={`${i}-${s.turn}`} className="click" data-active={i === index}
                  aria-current={i === index ? "true" : undefined} onClick={() => onPick(i)}>
                  <td className="r num">
                    <button className="linkish" aria-label={`Go to turn ${s.turn}`} onClick={(e) => { e.stopPropagation(); onPick(i); }}>
                      {s.turn}
                    </button>
                  </td>
                  {turns.size > 0 && (
                    <>
                      <td className="clip">{t ? clip(t.user) : <span className="muted">not recorded</span>}</td>
                      <td className="clip">{t ? clip(t.output) : <span className="muted">not recorded</span>}</td>
                    </>
                  )}
                  <td>
                    {missed.length > 0
                      ? <span style={{ color: "var(--red)" }}><span aria-hidden="true">▲ </span>Missed: {missed.join(", ")}</span>
                      : s.sensor_gaps.length > 0
                        ? <span className="muted"><span aria-hidden="true">○ </span>No reading: {s.sensor_gaps.join(", ")}</span>
                        : <span style={{ color: "var(--green)" }}><span aria-hidden="true">✓ </span>All met</span>}
                    {missed.length > 0 && s.sensor_gaps.length > 0 && (
                      <span className="muted"> · no reading: {s.sensor_gaps.join(", ")}</span>
                    )}
                  </td>
                  <td className="r num">{s.drift.toFixed(2)}</td>
                  <td>
                    {s.recovery_fired
                      ? <span><b>{s.recovery_fired.replace("_", "-")}</b></span>
                      : <span className="muted">no action</span>}
                    {t?.restated && <span className="muted"> · re-statement sent here</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
