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


def test_build_warns_when_the_control_plane_has_no_admin_token(caplog):
    import logging

    from proxy.server import build

    with caplog.at_level(logging.WARNING, logger="openguide.proxy"):
        build(ProxyConfig(admin_token=None))
    assert any("OPENGUIDE_ADMIN_TOKEN" in r.getMessage() for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="openguide.proxy"):
        build(ProxyConfig(admin_token="s3cret"))
    assert not any("OPENGUIDE_ADMIN_TOKEN" in r.getMessage() for r in caplog.records)


def test_content_capture_without_an_admin_token_refuses_to_start():
    import pytest

    from proxy.server import build

    with pytest.raises(RuntimeError, match="OPENGUIDE_ADMIN_TOKEN"):
        build(ProxyConfig(capture_content=True, admin_token=None))


def test_content_capture_with_a_token_starts():
    from proxy.server import build

    assert build(ProxyConfig(capture_content=True, admin_token="s3cret")) is not None


def test_content_capture_on_an_open_proxy_needs_an_explicit_override_and_says_so_loudly(caplog):
    import logging

    from proxy.server import build

    with caplog.at_level(logging.ERROR, logger="openguide.proxy"):
        assert build(ProxyConfig(capture_content=True, admin_token=None, allow_open_capture=True)) is not None
    assert any("readable by anyone" in r.getMessage() for r in caplog.records)


def test_the_override_is_read_from_the_environment(monkeypatch):
    assert ProxyConfig().allow_open_capture is False
    monkeypatch.setenv("OPENGUIDE_ALLOW_OPEN_CAPTURE", "1")
    assert ProxyConfig.from_env().allow_open_capture is True
