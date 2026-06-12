"""ASGI entrypoint: build a configured proxy app from the environment.

    uvicorn proxy.server:app --host 0.0.0.0 --port 8088

Wires a real HttpxUpstream, loads contracts from OPENGUIDE_CONTRACTS_DIR, and
selects an OTel exporter when OTEL_EXPORTER_OTLP_ENDPOINT is set (else an
in-memory emitter for local inspection at /v1/openguide/spans).
"""
from __future__ import annotations

from .app import create_app
from .config import ProxyConfig
from .otel import InMemorySpanEmitter
from .registry import ContractRegistry
from .upstream import HttpxUpstream


def build(config: ProxyConfig | None = None):
    config = config or ProxyConfig.from_env()
    registry = ContractRegistry()
    if config.contracts_dir:
        registry.load_dir(config.contracts_dir)
    upstream = HttpxUpstream(config.upstream_base_url, config.upstream_api_key)
    emitter = _build_emitter(config)
    return create_app(registry=registry, upstream=upstream, emitter=emitter)


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
