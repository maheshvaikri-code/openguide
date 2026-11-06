/** A key to the Fleet: what a square is, what its colour means, and what the marks on it mean. */
export function FleetGuide() {
  return (
    <details className="panel guide" open>
      <summary className="panel-summary"><h2>How to read this page</h2></summary>
      <div className="body guide-grid">
        <div className="stack">
          <p>
            <b>Each square is one run</b>: one conversation or agent session that the proxy governed under a contract.
            Select a square to see what happened in it; open it to replay it turn by turn.
          </p>
          <p>
            <b>The colour is the highest drift the run reached.</b> Drift measures how far the agent fell short of
            the contract's rules on a turn: for each rule, how far its reading fell below its minimum times its
            weight, added up and capped at 1. <b>0 means every rule held</b>; the higher it goes, the more rules were
            missed, or the worse they were missed.
          </p>
          <p className="muted">
            Each contract sets its own threshold for acting, so the same colour can mean different things for
            different contracts. Select a run to see its contract's threshold.
          </p>
        </div>
        <div className="stack">
          <div className="legend" aria-label="Colour scale">
            <span className="num">0</span><span className="ramp" aria-hidden="true" /><span className="num">1</span>
            <span>peak drift, all rules held to far off</span>
          </div>
          <ul className="key" aria-label="Marks on a square">
            <li><span className="swatch halted" aria-hidden="true" /><span><b>A dot</b> means the run is flagged halted in the record. The proxy records a halt; it does not itself block later requests.</span></li>
            <li><span className="swatch broken" aria-hidden="true" /><span><b>A red frame</b> means the run's trace no longer verifies: it was altered after it was written.</span></li>
            <li><span className="swatch fresh" aria-hidden="true" /><span><b>A cyan frame</b> means the run arrived while you were watching.</span></li>
          </ul>
        </div>
      </div>
    </details>
  );
}
