# ADR-002: Opt-in message capture as a `TURN` trace record

Status: accepted (the human asked for per-turn detail in the Console) · Gate: G1 · Owner: Chief Architect

## Context
The Console could show that a rule was missed on a turn, but not what the user asked, what the model
replied, or which re-anchor was sent, because traces held behavioral state only. That was deliberate: a
proxy sits on prompts and replies, which are often sensitive. But without the text, "what we detected" is
a number with no context, and reviewing a drifting run means guessing.

## Decision
Add an **opt-in** `TURN` record (spec/trace/README.md). Off by default; enabled with
`OPENGUIDE_CAPTURE_CONTENT=1` or `create_app(capture_content=True)`.

- It is appended after the turn's `STATE`, **inside the hash chain**, following the precedent of
  `TOOL_POLICY`. Captured text is therefore tamper-evident and verified by the same procedure.
- It records only the **newest user message**, the model's reply, and the re-anchor text sent. Never the
  system prompt or earlier history, which keeps the record small and avoids re-capturing the same text.
- Each field is clipped to 8000 characters with a `truncated` flag, so one huge message cannot bloat a chain.
- The metadata-only trace view never includes it.
- One builder, `guidancegrid.core.trace.turn_event`, is used by the proxy and by the experiment harness, so
  the format cannot diverge.

## Consequences
- + The Console can show the conversation, the rule-by-rule result and the re-anchor that was actually sent.
- + Experiment traces become self-contained evidence: the replies behind every number are in the chain.
- - A trace with capture on contains personal or confidential text. Retention, access and redaction are the
  operator's responsibility; the Console's admin-token protection applies, and the README says so.
- - Not retroactive: runs recorded without capture have no text. Saved experiment results can be replayed
  into traces with text (benchmarks/real_rebuild.py), checked turn by turn against the recording.

## Rejected
- Always capture: unacceptable default for a proxy in front of production traffic.
- Store text outside the chain (a side table): text could then be edited without breaking verification.
- Hash the text instead of storing it: tamper-evident but useless for the stated need.
