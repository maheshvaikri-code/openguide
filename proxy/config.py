"""Proxy configuration from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ProxyConfig:
    upstream_base_url: str = "https://api.openai.com"
    upstream_api_key: str | None = None
    contracts_dir: str | None = None
    otlp_endpoint: str | None = None
    store_dsn: str | None = None
    admin_token: str | None = None
    tool_allowlist: str | None = None
    tool_denylist: str | None = None
    tool_require_approval: str | None = None
    port: int = 8088
    packs_dir: str | None = None
    console_dir: str | None = None
    # Record each turn's user message, reply and re-anchor in the trace (off by default: privacy).
    capture_content: bool = False
    # Allow content capture on a proxy with no admin token (anyone who can reach it could read every prompt).
    allow_open_capture: bool = False

    @classmethod
    def from_env(cls) -> "ProxyConfig":
        return cls(
            upstream_base_url=os.environ.get("OPENGUIDE_UPSTREAM_BASE_URL", "https://api.openai.com"),
            upstream_api_key=os.environ.get("OPENGUIDE_UPSTREAM_API_KEY") or None,
            contracts_dir=os.environ.get("OPENGUIDE_CONTRACTS_DIR") or None,
            otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
            store_dsn=os.environ.get("OPENGUIDE_STORE_DSN") or None,
            admin_token=os.environ.get("OPENGUIDE_ADMIN_TOKEN") or None,
            tool_allowlist=os.environ.get("OPENGUIDE_TOOL_ALLOWLIST") or None,
            tool_denylist=os.environ.get("OPENGUIDE_TOOL_DENYLIST") or None,
            tool_require_approval=os.environ.get("OPENGUIDE_TOOL_REQUIRE_APPROVAL") or None,
            port=int(os.environ.get("OPENGUIDE_PORT", "8088")),
            packs_dir=os.environ.get("OPENGUIDE_PACKS_DIR") or None,
            console_dir=os.environ.get("OPENGUIDE_CONSOLE_DIR") or None,
            capture_content=os.environ.get("OPENGUIDE_CAPTURE_CONTENT", "").strip().lower()
            in ("1", "true", "yes", "on"),
            allow_open_capture=os.environ.get("OPENGUIDE_ALLOW_OPEN_CAPTURE", "").strip().lower()
            in ("1", "true", "yes", "on"),
        )
