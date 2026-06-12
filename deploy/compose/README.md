# Local stack (docker compose)

The OSS experience: proxy + Jaeger (OTLP) + postgres, one command.

```bash
export OPENAI_API_KEY=sk-...          # or point OPENGUIDE_UPSTREAM_BASE_URL elsewhere
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
| postgres | 5432 | fleet index + CAS (store) |

Inspect a session directly: `GET http://localhost:8088/v1/openguide/sessions/<id>`.
Without OTLP configured, spans are kept in memory at `GET /v1/openguide/spans`.
