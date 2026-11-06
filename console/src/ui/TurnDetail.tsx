import { ACTION_MEANING, detectionRows, explainedDrift, ladderSteps, type ContractInfo, type DetectionRow, type RuleStatus } from "../lib/contractInfo";
import type { StateRecord, SteerRecord, TurnRecord } from "../lib/types";
import { fmt } from "./format";

const RESULT: Record<RuleStatus, { glyph: string; text: string; color: string }> = {
  met: { glyph: "✓", text: "Met", color: "var(--green)" },
  missed: { glyph: "▲", text: "Missed", color: "var(--red)" },
  "no-reading": { glyph: "○", text: "No reading", color: "var(--muted)" },
  "not-scored": { glyph: "–", text: "Not scored", color: "var(--muted)" },
  "not-checked": { glyph: "○", text: "Not checked", color: "var(--muted)" },
};

function Result({ row }: { row: DetectionRow }) {
  const r = RESULT[row.status];
  // A hard rule reads Passed / Failed only when it was actually checked; "no reading" and "not checked" stand.
  const text = row.hard && row.status === "missed" ? "Failed" : row.hard && row.status === "met" ? "Passed" : r.text;
  return <span style={{ color: r.color }}><span aria-hidden="true">{r.glyph} </span>{text}</span>;
}

/** Everything about one turn: what was said, what the sensors detected, and what the contract did. */
export function TurnDetail({
  state,
  turn,
  steer,
  info,
  anyContent,
}: {
  state: StateRecord;
  turn: TurnRecord | undefined;
  /** Set when this turn's generation was steered at the model's activations (T0). */
  steer?: SteerRecord | undefined;
  info: ContractInfo;
  /** Whether ANY turn of this run has recorded text (so a gap here isn't mistaken for capture being off). */
  anyContent: boolean;
}) {
  const rows = detectionRows(state, info);
  const explained = explainedDrift(rows);
  const matches = explained !== null && Math.abs(explained - state.drift) < 0.0015;
  const steps = ladderSteps(info, state.drift, state.recovery_fired);

  return (
    <section className="panel turn-detail" aria-label={`Details of turn ${state.turn}`}>
      <header>
        <h2>What happened on turn {state.turn}</h2>
      </header>
      <div className="body stack">
        <div>
          <h3>What was said</h3>
          {turn ? (
            <div className="stack" style={{ marginTop: 8 }}>
              <div className="say user"><span className="who">The latest user message in this request</span><p>{turn.user || "(empty)"}</p></div>
              {turn.restated && (
                <div className="say restated">
                  <span className="who">Persona and boundaries re-stated to the model with this request</span>
                  <p>{turn.restated}</p>
                </div>
              )}
              <div className="say model"><span className="who">The model replied</span><p>{turn.output || "(empty reply)"}</p></div>
              {turn.truncated && <p className="muted">Long text was clipped when it was recorded.</p>}
            </div>
          ) : anyContent ? (
            <p className="notice" style={{ marginTop: 8 }}>
              No text was recorded for this turn. The sensor results below are always recorded.
            </p>
          ) : (
            <p className="notice" style={{ marginTop: 8 }}>
              This trace holds no message text. The proxy records it only when started with{" "}
              <code>OPENGUIDE_CAPTURE_CONTENT=1</code>, which is off by default because traces would then contain
              prompts and replies. The sensor results below are always recorded.
            </p>
          )}
        </div>

        {steer && (
          <p className="notice" aria-label="Activation steering">
            <b>Activation steering was on for this turn</b> (peak gain {steer.gain}, layers {steer.band[0]} to {steer.band[1] - 1}),
            because the previous turn needed a correction. The model's internal activations were nudged toward the
            rules while it wrote this reply, in addition to any reminder above.
          </p>
        )}

        <div>
          <h3>What the sensors detected</h3>
          <table className="detect" aria-label="Rule results for this turn">
            <thead>
              <tr>
                <th>Rule</th><th>Measured by</th><th className="r">Reading</th><th className="r">Must be at least</th>
                <th>Result</th><th className="r">Added to drift</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} data-missed={r.status === "missed"}>
                  <td className="mono">{r.id}</td>
                  <td>{r.kind ?? <span className="muted">unknown</span>}{r.hard && <span className="muted"> (hard rule)</span>}</td>
                  <td className="r num">{r.reading === null ? "none" : fmt(r.reading)}</td>
                  <td className="r num">{r.hard ? "pass or fail" : r.floor === null ? "–" : fmt(r.floor)}</td>
                  <td><Result row={r} /></td>
                  <td className="r num">
                    {r.contribution !== null ? r.contribution.toFixed(2) : r.shortfall !== null && r.shortfall > 0 ? `short by ${r.shortfall.toFixed(2)}` : "0.00"}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={5}><b>Drift this turn</b></td>
                <td className="r num"><b>{state.drift.toFixed(2)}</b></td>
              </tr>
            </tfoot>
          </table>
          <p className="muted" style={{ marginTop: 8 }}>
            {matches
              ? "Drift is each rule's weight times how far it fell below its minimum, added up (capped at 1). A rule with no reading adds nothing."
              : explained === null
                ? "This contract's weights couldn't be read, so the drift can't be broken down here. It is the recorded value."
                : `The columns add up to ${explained.toFixed(2)}, but the recorded drift is ${state.drift.toFixed(2)}. The breakdown may be missing a default or a rounding.`}
          </p>
          {state.sensor_gaps.length > 0 && (
            <p className="notice">No reading was produced for {state.sensor_gaps.join(", ")}. The run carried on, and that rule added nothing to drift.</p>
          )}
          {state.validation_failures.length > 0 && (
            <p className="notice bad">Hard rule failed: {state.validation_failures.join(", ")}. A failed hard rule triggers a re-anchor if no response step already does.</p>
          )}
        </div>

        <div>
          <h3>What the contract did</h3>
          {steps.length === 0 ? (
            <p className="muted">This contract's response steps couldn't be read.</p>
          ) : (
            <ol className="ladder" aria-label="Response steps">
              {steps.map((s, i) => (
                <li key={`${i}-${s.action}`} data-reached={s.reached}>
                  <span className="rung" aria-hidden="true">{s.reached ? "●" : "○"}</span>
                  <span>
                    <b>{s.action.replace("_", "-")}</b> at drift ≥ {s.gate}
                    {s.defaulted ? " (the default; the contract states no gate)" : ""}
                    {s.fired ? " — reached, and recorded for this turn" : s.reached ? " — reached" : " — not reached"}
                    {ACTION_MEANING[s.action] && <span className="muted">. {ACTION_MEANING[s.action]}</span>}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <p style={{ marginTop: 8 }}>
            {state.recovery_fired
              ? <>Action taken this turn: <b>{state.recovery_fired.replace("_", "-")}</b>.{state.reanchored ? " A re-statement of the rules was prepared for the next request." : ""}</>
              : state.reanchored
                ? <span className="muted">No action was taken this turn, but a re-statement was still prepared for the next request (on schedule or by a trigger).</span>
                : <span className="muted">No action was taken this turn.</span>}
          </p>
        </div>
      </div>
    </section>
  );
}
