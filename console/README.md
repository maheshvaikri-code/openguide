# OpenGuide Console

A dashboard for the OpenGuide proxy: see a fleet drift, replay a governed run to the
moment a correction fired, and verify that a trace has not been altered.

Vite + React + TypeScript. It only reads the proxy's REST API (`/v1/openguide/*`);
there is no privileged path. See `docs/adr/001-console-stack.md` for why this stack
and `docs/briefs/console.md` for scope.

## Run the demo (one command)

```bash
make console-demo        # needs Node 20+ and the Python dev install
```

Then open <http://127.0.0.1:8088/console/>. This builds the Console, seeds a
**simulated** fleet (every model id is `mock:*` and the UI says so), and serves the
proxy and the Console from one process. A few runs arrive every few seconds so the
Fleet's live updates have something to show.

Good first clicks: Fleet, then the run `demo-governed-sparse`, then "Compare with"
`demo-baseline-sparse`, then "Jump to first correction". For the integrity story, open
Audit and compare `demo-governed-sparse` (verified) with `demo-tampered` (the Console
names the record that was altered).

## Pages

| Page | What it answers |
|------|-----------------|
| Fleet | Which runs drifted, and which contract/model are they on? |
| Run replay | What happened, turn by turn, and when did a correction fire? |
| Trajectory | Where did the run travel relative to the contract's safe region? (3D) |
| Contracts | What does a contract say, what differs between two, how do I activate one? |
| Packs | Which steering packs exist, and what has actually been measured on them? |
| Audit | Is this record intact? Printable report. |

## Against a real proxy

```bash
OPENGUIDE_CONSOLE_DIR=console/dist OPENGUIDE_PACKS_DIR=packs \
  uvicorn proxy.server:app --port 8088
```

If `OPENGUIDE_ADMIN_TOKEN` is set the Console asks for it; it is kept in
`sessionStorage` (this tab only).

## Seeing what was said

The replay shows, for each turn: what the user asked, what the model replied, which rules the sensors checked
and how far each fell short, how that adds up to the turn's drift, and what the contract did about it. The
message text appears only if the proxy recorded it: start the proxy with `OPENGUIDE_CAPTURE_CONTENT=1`. It is
**off by default** because the text is the prompts and replies themselves (see `docs/adr/002-opt-in-content-capture.md`).
Without it the sensor results and drift arithmetic still show.

On the Fleet, the squares are laid out as one grid. Click a square and its panel on the right opens three
collapsible parts: *Why this colour* (what drift is, this run's peak against its own contract's gate, and what
each mark on the square means, only the marks it actually has), *What was detected in this run* (read from its
own trace: turns at or above the gate, when the first correction fired, whether drift came back down, and a
per-rule table of how often each rule was missed) and *Run details*. Runs named alike (`arm-a-s0`, `arm-a-s1`,
...) can optionally be grouped with "By series", which appears only when the runs form several series.

## Security

**The proxy is unauthenticated unless `OPENGUIDE_ADMIN_TOKEN` is set.** With no token, anyone who can
reach it can read every stored trace (which contain prompts and responses), list runs and contracts,
and register contracts. The proxy logs a warning at startup and the Console shows a notice when this
is the case. Set a token before exposing the proxy beyond your own machine, and put TLS in front of it.

- The Console keeps the token in `sessionStorage` (this tab only) and sends it as a bearer header.
- Prefer the `OPENGUIDE_ADMIN_TOKEN` environment variable to the `--admin-token` flag, which is visible in process listings.
- Request bodies to the contract endpoints are capped at 256 KB, and `limit` on the runs query is 1 to 10 000.
- The audit page's "Hash chain consistent" shows a record was not altered after it was written. It does not prove who
  wrote it, and the head is stored with the records. Anchor or sign the head externally if you need that.

## Develop

```bash
cd console
npm ci
npm run dev          # http://localhost:5173/console/, proxies /v1 to 127.0.0.1:8088
npm run typecheck
npm test
npm run build        # -> console/dist, served by the proxy at /console/
```

Pure logic lives in `src/lib` (API client, replay, projection, diff, heat layout,
router) and is unit-tested; pages are in `src/pages`; shared pieces in `src/ui`.
Every page handles loading, error, empty, partial and success states.

## Honest scope

- The demo data is simulated; the control path and traces are real, the agent is not.
- Fleet cells show per-run summaries. Per-turn series come from a run's stored trace,
  so runs that exist only in the fleet index have no replay.
- The hash chain shows a record was not changed after it was written. It does not
  prove who wrote it.
- Contracts are edited as JSON (the form the proxy stores). TOML editing and a
  "what changed Tuesday" fleet diff are deferred.
- Fonts are system fonts so the demo works offline.
