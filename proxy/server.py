"""ASGI entrypoint: build a configured proxy app from the environment.

    uvicorn proxy.server:app --host 0.0.0.0 --port 8088

Wires a real HttpxUpstream, loads contracts from OPENGUIDE_CONTRACTS_DIR, and
selects an OTel exporter when OTEL_EXPORTER_OTLP_ENDPOINT is set (else an
in-memory emitter for local inspection at /v1/openguide/spans).
"""
from __future__ import annotations

import logging

from .app import create_app
from .config import ProxyConfig
from .otel import InMemorySpanEmitter
from .registry import ContractRegistry
from .tool_policy import ToolPolicy
from .upstream import HttpxUpstream

log = logging.getLogger("openguide.proxy")


def build(config: ProxyConfig | None = None):
    config = config or ProxyConfig.from_env()
    if not config.admin_token:
        log.warning(
            "OPENGUIDE_ADMIN_TOKEN is not set: /v1/openguide/* (traces, contracts, runs) is open to "
            "anyone who can reach this proxy, and contracts can be registered without credentials. "
            "Set a token before exposing the proxy beyond localhost."
        )
    if config.capture_content and not config.admin_token:
        if not config.allow_open_capture:
            raise RuntimeError(
                "OPENGUIDE_CAPTURE_CONTENT is on but OPENGUIDE_ADMIN_TOKEN is not set: every prompt "
                "and reply would be readable by anyone who can reach this proxy. Set a token, or set "
                "OPENGUIDE_ALLOW_OPEN_CAPTURE=1 to accept this on a machine nobody else can reach."
            )
        log.error("CONTENT CAPTURE IS ON WITH NO ADMIN TOKEN: full prompts and replies are readable by "
                  "anyone who can reach this proxy.")
    registry = ContractRegistry()
    if config.contracts_dir:
        registry.load_dir(config.contracts_dir)
    upstream = HttpxUpstream(config.upstream_base_url, config.upstream_api_key)
    emitter = _build_emitter(config)
    store = _build_store(config)
    tool_policy = ToolPolicy.from_csv(
        allow=config.tool_allowlist,
        deny=config.tool_denylist,
        require_approval=config.tool_require_approval,
    )
    return create_app(
        registry=registry,
        upstream=upstream,
        emitter=emitter,
        store=store,
        admin_token=config.admin_token,
        tool_policy=tool_policy,
        packs_dir=config.packs_dir,
        console_dir=config.console_dir,
        capture_content=config.capture_content,
    )


def _build_store(config: ProxyConfig):
    """Build the fleet-index store.

    Supported DSNs today:
      - unset / empty: in-memory sqlite
      - sqlite:<path>: file-backed sqlite, or sqlite: for in-memory

    Unsupported DSNs fail fast so deployments do not accidentally believe they
    have durable storage while using an in-memory fallback.
    """
    from guidancegrid.store import Store

    dsn = config.store_dsn
    if not dsn:
        return Store(":memory:")
    if dsn.startswith("sqlite:"):
        return Store(dsn[len("sqlite:"):] or ":memory:")
    raise ValueError(f"unsupported OPENGUIDE_STORE_DSN {dsn!r}; only sqlite: DSNs are supported")


def _build_emitter(config: ProxyConfig):
    if not config.otlp_endpoint:
        return InMemorySpanEmitter()
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from .otel import OTLPSpanEmitter

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=config.otlp_endpoint)))
        trace.set_tracer_provider(provider)
        return OTLPSpanEmitter(trace.get_tracer("openguide.proxy"))
    except Exception:
        # OTel not installed / misconfigured: fall back, never block the data plane
        return InMemorySpanEmitter()


app = build()
