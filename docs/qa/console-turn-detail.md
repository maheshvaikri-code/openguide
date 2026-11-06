# QA + Security Report: per-turn detail and Fleet explanations (opt-in content capture)

**Reviews:** security review and code review by independent reviewer agents (read-only), then fixes and re-test.
**Scope:** `TURN` trace record and `OPENGUIDE_CAPTURE_CONTENT` (ADR-002), Console Run replay detail, Fleet
explanations (in the selected-run panel) and the optional series view, `benchmarks/real_rebuild.py`.

## What was asked
"More details on each turn and what we detected is not seen, and the blocks in Fleet need more information to
explain."

## Verification
- `python -m pytest` -> **449 passed**; `ruff check .` clean.
- `npm --prefix console test` -> **172 passed**, stable over three runs; `npm run typecheck` and `npm run build` clean.
- **Fidelity of the rebuilt real runs:** all 40 saved runs (25 recovery, 15 ablation) were replayed through the
  harness and reproduced the recorded drift, action, re-anchor and rule results exactly, turn by turn. A rebuild
  that differs refuses to write (tested).
- **Reproducibility:** regenerating the steered conversations on the GPU reproduced the original per-conversation
  scores exactly (greedy decoding), for every gain checked.

## Security review: verdict SIGN-OFF (no critical or high findings)
Confirmed: capture is off by default on every path including streaming; no endpoint exposes text beyond the existing
trace endpoint; the metadata-only view never includes it; the admin guard covers every route that returns a trace;
captured text is rendered as React text with no HTML injection path; the system prompt, earlier history and tool-call
arguments are never recorded; text is inside the hash chain and editing it breaks verification.

| Finding | Severity | Disposition |
|---|---|---|
| Capture could be enabled on a proxy with no admin token, making every prompt readable by anyone | Medium | **Fixed.** The proxy refuses to start unless `OPENGUIDE_ALLOW_OPEN_CAPTURE=1`, and then logs an error. Tested. |
| A non-string text part in a request crashed the data plane (500) when capture was on, leaving the run half-written | Medium | **Fixed.** Only string text is recorded; a failure while recording is caught and logged and can never break the response. Tested, including a recording failure. |
| Bidirectional control characters in captured text | Low | **Fixed** (`unicode-bidi: isolate`). |
| Word lock file (`~$*.docx`) not ignored | Low | **Fixed** (`.gitignore`). |
| Captured text is unencrypted at rest; no purge path | Low | **Accepted.** Retention and redaction are the operator's, as ADR-002 states. |
| Storage grows with turns (a trace snapshot per turn) | Info | **Accepted.** Same shape as before capture; text multiplies the bytes. |
| No CSP header on the `/console` mount | Info | **Accepted.** Text is rendered inert; noted as cheap defence in depth. |

## Code review: verdict REQUEST-CHANGES, no blockers; all majors fixed
The project rule is never to overstate, and several explanations stated more than the data proves.

| Finding | Disposition |
|---|---|
| "halt: Stop the run" and "escalate: hand to a person" are not what the code does (the reconciler records a flag; the proxy never blocks later requests) | **Fixed.** Wording now says what is recorded: halt "marks the run as halted in the record; the proxy does not itself stop later requests"; escalate "no hand-off happens by itself"; Fleet says "flagged halted". Pinned by tests. |
| A hard rule could read "Passed" with no basis (no reading, an unvalidated measure, or a floor-based flag) | **Fixed.** Shows "No reading" / "Not checked" / "pass or fail"; the missed-rules list judges a hard rule by validation, not a floor. A test caught that the display still overrode the status; fixed. |
| A turn with a missing reading was listed "All met" | **Fixed.** Shows "No reading: x". |
| Every captured run showed a false banner "N records were not behavioral-state records and are left out" | **Fixed.** TURN records are not counted as left out. |
| Series figures presented a filtered subset as the series' average | **Fixed.** A notice says so when filters are on; counts say "shown". |
| Series naming merged unrelated runs (`gpt-3`/`gpt-4`, dated ids, `sweep-gain-5`/`-10`) | **Fixed.** Only `-s<N>` seeds and long zero-padded counters are stripped. |
| Layout flipped by itself as live runs arrived | **Fixed.** Decided once; tested under polling. |
| "Chain broken" and "arrived" shown by outline colour only | **Fixed.** Said in each square's label and tooltip. |
| Omitted weight / threshold shown as unknown (schema defaults are 1.0) | **Fixed.** Defaults applied and labelled. |
| Several ladder steps "reached" with no sign of which fired | **Fixed.** The recorded step is marked. |
| Text that the data does not prove ("the sensor failed or timed out", "the contract may have changed", "rules re-stated" for what is persona and boundaries) | **Fixed.** Reworded. |
| "No text recorded" shown for the whole trace when only one turn lacked text | **Fixed.** |
| Duplicate turn numbers; list-row keys; active row not marked for assistive technology | **Fixed.** |

**Not fixed, recorded:**
- On an agent tool-loop turn, "the latest user message" can be an earlier prompt and a reply that is only tool calls
  shows "(empty reply)"; a turn denied by tool policy is recorded as replied. The label now says "latest user message
  in this request"; recording the last message's role, the tool-call names and a denial is a separate change.
- Rebuilt runs do not say in their manifest that they were replayed from saved replies (a `rebuilt_from` field would
  let the Audit page say so).
- The fidelity check compares per-turn drift, action, re-anchor and rule results, not each invariant's raw reading.
