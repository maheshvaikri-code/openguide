"""AC1: the proxy serves the built Console at /console and stays healthy."""
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.upstream import MockUpstream


def _app(console_dir):
    return create_app(upstream=MockUpstream(lambda b: "ok"), console_dir=console_dir)


def test_console_served_when_built(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>OpenGuide Console</title>",
                                         encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log(1)", encoding="utf-8")
    c = TestClient(_app(str(tmp_path)))
    r = c.get("/console/")
    assert r.status_code == 200 and "OpenGuide Console" in r.text
    assert c.get("/console/app.js").status_code == 200
    assert c.get("/healthz").json() == {"status": "ok"}


def test_console_redirects_bare_path(tmp_path):
    (tmp_path / "index.html").write_text("<title>x</title>", encoding="utf-8")
    c = TestClient(_app(str(tmp_path)))
    r = c.get("/console", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308) and r.headers["location"].endswith("/console/")


def test_no_console_mount_when_missing(tmp_path):
    c = TestClient(_app(str(tmp_path / "does-not-exist")))
    assert c.get("/console/").status_code == 404
    assert c.get("/healthz").status_code == 200       # proxy unaffected


def test_no_console_mount_without_index(tmp_path):
    c = TestClient(_app(str(tmp_path)))                # dir exists but empty
    assert c.get("/console/").status_code == 404
