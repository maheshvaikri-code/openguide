"""Proxy server configuration."""
from proxy.config import ProxyConfig
from proxy.server import _build_store


def test_config_loads_tool_policy_environment(monkeypatch):
    monkeypatch.setenv("OPENGUIDE_TOOL_ALLOWLIST", "search,crm.read")
    monkeypatch.setenv("OPENGUIDE_TOOL_DENYLIST", "crm.delete")
    monkeypatch.setenv("OPENGUIDE_TOOL_REQUIRE_APPROVAL", "payments.*")

    cfg = ProxyConfig.from_env()

    assert cfg.tool_allowlist == "search,crm.read"
    assert cfg.tool_denylist == "crm.delete"
    assert cfg.tool_require_approval == "payments.*"


def test_build_store_defaults_to_in_memory_sqlite():
    store = _build_store(ProxyConfig())
    try:
        assert store.conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        store.close()


def test_build_store_accepts_sqlite_dsn(tmp_path):
    db = tmp_path / "openguide.db"
    store = _build_store(ProxyConfig(store_dsn=f"sqlite:{db}"))
    try:
        assert db.exists()
        assert store.conn.execute("SELECT name FROM sqlite_master").fetchall()
    finally:
        store.close()


def test_build_store_rejects_unsupported_dsn():
    try:
        _build_store(ProxyConfig(store_dsn="postgresql://example/db"))
    except ValueError as exc:
        assert "only sqlite: DSNs are supported" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unsupported DSN should fail fast")
