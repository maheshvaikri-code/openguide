# Local stack (docker compose)

The OSS experience: proxy + Jaeger (OTLP) + a persisted sqlite store, one
command.

```bash
export OPENAI_API_KEY=sk-...          # or point OPENGUIDE_UPSTREAM_BASE_URL elsewhere
export OPENGUIDE_ADMIN_TOKEN=change-me # optional: protects /v1/openguide/* endpoints
export OPENGUIDE_TOOL_DENYLIST=crm.delete,payments.* # optional tool-call gate
docker compose -f deploy/compose/docker-compose.yml up
```

Then point any OpenAI SDK app at `http://localhost:8088/v1` and add one header,
`X-OpenGuide-Contract: <hash>` (contracts in `spec/obc/examples/` are loaded at
startup; list them via the registry). Behavioral state appears in Jaeger at
<http://localhost:16686> within a few seconds — **zero app code changes.**

| Service | Port | What |
|---------|------|------|
| proxy | 8088 | OpenAI-compatible proxy with header-activated governance |
| jaeger | 16686 (UI), 4317 (OTLP) | trace backend for `gen_ai.behavior.*` spans |
| sqlite volume | n/a | persisted fleet index + CAS at `/data/openguide.db` |

Inspect a session directly: `GET http://localhost:8088/v1/openguide/sessions/<id>`.
Fetch a full trace at `GET /v1/openguide/runs/<id>/trace`, or a verification
summary without raw records at `GET /v1/openguide/runs/<id>/trace?metadata_only=true`.
If `OPENGUIDE_ADMIN_TOKEN` is set, pass either
`Authorization: Bearer <token>` or `X-OpenGuide-Admin-Token: <token>` when
calling `/v1/openguide/*` control-plane endpoints. Chat completions and
`/healthz` are not admin-token protected.
Without OTLP configured, spans are kept in memory at `GET /v1/openguide/spans`.

Optional tool-call policy gates are configured with comma-separated function
name patterns:

- `OPENGUIDE_TOOL_ALLOWLIST`: only these tool names may pass.
- `OPENGUIDE_TOOL_DENYLIST`: these tool names are denied.
- `OPENGUIDE_TOOL_REQUIRE_APPROVAL`: these tool names are denied with an
  `approval_required:*` reason until a real approval workflow is wired in.

When a governed assistant message proposes a tool call, OpenGuide records a
`TOOL_POLICY` event in the trace with the tool id, tool name, decision, and
reason. Tool arguments are not stored in that audit event.

Postgres is not wired in this reference stack yet; the current proxy store
backend supports `sqlite:` DSNs. Self-hosted Postgres remains a roadmap item for
enterprise deployments.
