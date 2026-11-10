"""Step 1 makes no network call and has no Anthropic client (docs/briefs/arch-drift-harness.md, AC 10).

``egress.py`` is the one deliberate exception: an allowlisting proxy that the launcher
will run in a sidecar container in a later step. It is never started here, and nothing
else in the package may import it (checked below).
"""
import ast
import pathlib

import pytest

PKG = pathlib.Path(__file__).resolve().parent.parent / "archstudy"
BANNED = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "anthropic", "ftplib",
          "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "websockets", "asyncio"}
EXEMPT = {"egress.py"}
LAUNCHER_ONLY = ("api.anthropic.com",)


def package_files():
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel.startswith(("codebase/", "acceptance/")) or "__pycache__" in rel:
            continue                         # the agent's codebase and the hidden tests are not the harness
        yield rel, path


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


@pytest.mark.parametrize("rel,path", [(r, p) for r, p in package_files() if r not in EXEMPT])
def test_the_harness_module_imports_no_network_library(rel, path):
    bad = {m for m in imports(path) if m.split(".")[0] in BANNED}
    assert not bad, f"{rel} imports {sorted(bad)}"


def test_nothing_imports_the_egress_proxy():
    for rel, path in package_files():
        if rel in EXEMPT:
            continue
        assert not any(m.split(".")[-1] == "egress" or m == "archstudy.egress" for m in imports(path)), rel
        source = path.read_text(encoding="utf-8")
        for host in LAUNCHER_ONLY:
            if rel not in ("isolation.py",):
                assert host not in source, f"{rel} names {host}"


def test_no_module_starts_a_session_or_calls_an_api():
    for rel, path in package_files():
        source = path.read_text(encoding="utf-8")
        assert ("claude -p" not in source and "messages.create" not in source
                and "api/messages" not in source), rel


def test_the_launcher_helper_only_builds_and_validates_a_command(monkeypatch):
    import subprocess

    from archstudy import isolation

    def boom(*a, **k):
        raise AssertionError("step 1 must not execute anything")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    argv = isolation.launch(image="archstudy-agent", name="t", workspace=pathlib.Path("/tmp/ws").resolve(),
                            snapshot_store=pathlib.Path("/tmp/snap").resolve(), network="archstudy-internal",
                            proxy_url="http://egress:3128", arm="B", command=["claude", "--version"])
    assert isinstance(argv, list) and argv[0] == "docker"
