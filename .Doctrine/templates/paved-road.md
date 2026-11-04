# Paved Road: <capability name>
<!-- G1 artifact — platform design. File as docs/platform/<capability>-road.md.
     One road per file. Owner: Platform Engineer; Chief Architect co-signs shared substrate. -->

> A paved road is the one supported, self-service way to do a common thing.
> One file per road; keep it short. Owner: Platform Engineer
> (`skills/platform-engineering.md`).

- **Capability:** <the common need — e.g. "deploy a web service">
- **Status:** proposed | supported | deprecated
- **Owner:** <platform engineer / team>
- **Consumers:** <the ≥2 real teams/repos using it — one consumer = not yet a road>
- **Version / contract:** <substrate version + where the contract lives>

## The guarantee
<What a team gets by taking this road: what it wires by default (doctrine
standards, observability, secrets handling) and what they no longer have to
decide.>

## How to use it (self-service)
<The one command / template / SDK call. Must be runnable without filing a
ticket.>

```bash
<one-command example>
```

## What it wires by default
- <standard / check / telemetry / secret-handling that comes for free>

## The escape hatch
<How a team opts out or customizes — every road has one. A team needing to
leave is a gap to close, not a violation.>

- **Opt-outs observed:** <who left, why → platform backlog>

## Promotion / lifecycle
<local → preview → prod ladder (deploy roads), or the version/upgrade policy
(library/SDK roads). Elevation to paid/external = §5 escalation.>
