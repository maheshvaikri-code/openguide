"""scripts/console_demo.py: builds a working app, and refuses a busy port cleanly."""
import importlib.util
import os
import socket

from fastapi.testclient import TestClient

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "console_demo.py")


def _load():
    spec = importlib.util.spec_from_file_location("console_demo_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_app_serves_seeded_data_without_a_db_file(tmp_path):
    demo = _load()
    app, seeded = demo.build_app(str(tmp_path), 5, None)
    c = TestClient(app)
    assert len(c.get("/v1/openguide/runs?limit=100").json()["runs"]) == 5 + len(seeded.featured)
    assert not list(tmp_path.glob("*.db"))            # in-memory: nothing to lock or leave stale


def test_port_is_free_detects_a_busy_port():
    demo = _load()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        assert demo.port_is_free("127.0.0.1", port) is False
    assert demo.port_is_free("127.0.0.1", port) is True
