"""WP7 / AC 8: the container launch command is built purely and validated fail closed.

Every rule gets a mutation test: corrupt exactly one property of a known-good argv and expect
IsolationError. No Docker daemon is needed except for the last test, which skips cleanly without one.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from archstudy.isolation import IsolationError, docker_run_argv, launch, validate_argv

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "archstudy" / "container" / "Dockerfile"
MANAGED = ROOT / "archstudy" / "container" / "managed-settings.json"
ARCH_DIR = ROOT / "archstudy"
# Built at runtime so no key-shaped literal exists in the repository.
FAKE_KEY = "sk-" + "ant-" + "x" * 12


def _docker_ok(*args: str) -> bool:
    try:
        done = subprocess.run(["docker", *args], capture_output=True, timeout=8)
    except Exception:
        return False
    return done.returncode == 0


def _image_present(image: str) -> bool:
    return _docker_ok("image", "inspect", image)


@pytest.fixture
def good(tmp_path: Path) -> list[str]:
    workspace = tmp_path / "ws"
    snaps = tmp_path / "snaps"
    workspace.mkdir()
    snaps.mkdir()
    return docker_run_argv(
        image="archstudy-agent:test",
        name="arch-run-1",
        workspace=workspace,
        snapshot_store=snaps,
        network="arch-internal",
        proxy_url="http://egress:3128",
        arm="B",
        command=["claude", "-p", "go"],
    )


def _drop(argv: list[str], flag: str, with_value: bool = True) -> list[str]:
    out = list(argv)
    i = out.index(flag)
    del out[i : i + (2 if with_value else 1)]
    return out


def _replace(argv: list[str], flag: str, value: str) -> list[str]:
    out = list(argv)
    out[out.index(flag) + 1] = value
    return out


def _insert_before_image(argv: list[str], *extra: str) -> list[str]:
    out = list(argv)
    i = out.index("archstudy-agent:test")
    out[i:i] = list(extra)
    return out


def _drop_env(argv: list[str], prefix: str) -> list[str]:
    out = list(argv)
    i = next(i for i, t in enumerate(out) if t.startswith(prefix))
    del out[i - 1 : i + 1]
    return out


def _set_mount(argv: list[str], target: str, spec: str) -> list[str]:
    out = list(argv)
    out[_mount_index(out, target)] = spec
    return out


def _mount_src(argv: list[str], target: str) -> str:
    return argv[_mount_index(argv, target)].rsplit(f":{target}:rw", 1)[0]


def _mount_index(argv: list[str], target: str) -> int:
    for i, token in enumerate(argv):
        if token == "-v" and argv[i + 1].endswith(f":{target}:rw"):
            return i + 1
    raise AssertionError(target)


def test_valid_argv_passes_and_has_expected_shape(good):
    validate_argv(good)
    assert good[:3] == ["docker", "run", "--rm"]
    assert good[good.index("--user") + 1] == "10001:10001"
    assert "ARCH_ARM=B" in good and "HTTPS_PROXY=http://egress:3128" in good
    assert good[-3:] == ["claude", "-p", "go"]


def test_builder_rejects_bad_arm_and_relative_paths(tmp_path):
    base = dict(
        image="img:1",
        name="n",
        workspace=tmp_path,
        snapshot_store=tmp_path / "s",
        network="net",
        proxy_url="http://p:1",
        arm="A",
        command=["x"],
    )
    assert docker_run_argv(**base)[0] == "docker"
    for bad in ("D", "a", "", "AB"):
        with pytest.raises(IsolationError):
            docker_run_argv(**{**base, "arm": bad})
    with pytest.raises(IsolationError):
        docker_run_argv(**{**base, "workspace": Path("relative/ws")})
    with pytest.raises(IsolationError):
        docker_run_argv(**{**base, "snapshot_store": Path("relative/snap")})
    with pytest.raises(IsolationError):
        docker_run_argv(**{**base, "env_names": ("ANTHROPIC_API_KEY=" + FAKE_KEY,)})


@pytest.mark.parametrize("arm", ["A", "B", "C"])
def test_each_arm_builds_a_valid_argv(tmp_path, arm):
    argv = launch(
        image="img:1",
        name="n",
        workspace=tmp_path / "w",
        snapshot_store=tmp_path / "s",
        network="net",
        proxy_url="http://p:3128",
        arm=arm,
        command=["claude"],
    )
    assert f"ARCH_ARM={arm}" in argv


MUTATIONS = {
    "no --read-only": lambda a: _drop(a, "--read-only", with_value=False),
    "uid 0": lambda a: _replace(a, "--user", "0:0"),
    "uid 0 only": lambda a: _replace(a, "--user", "0"),
    "gid 0": lambda a: _replace(a, "--user", "10001:0"),
    "user root name": lambda a: _replace(a, "--user", "root"),
    "no --user": lambda a: _drop(a, "--user"),
    "cap-drop not ALL": lambda a: _replace(a, "--cap-drop", "NET_ADMIN"),
    "no --cap-drop": lambda a: _drop(a, "--cap-drop"),
    "cap-add": lambda a: _insert_before_image(a, "--cap-add", "SYS_ADMIN"),
    "no no-new-privileges": lambda a: _drop(a, "--security-opt"),
    "seccomp unconfined": lambda a: _replace(a, "--security-opt", "seccomp=unconfined"),
    "no pids limit": lambda a: _drop(a, "--pids-limit"),
    "pids unlimited": lambda a: _replace(a, "--pids-limit", "-1"),
    "pids zero": lambda a: _replace(a, "--pids-limit", "0"),
    "no memory": lambda a: _drop(a, "--memory"),
    "memory zero": lambda a: _replace(a, "--memory", "0"),
    "no cpus": lambda a: _drop(a, "--cpus"),
    "cpus zero": lambda a: _replace(a, "--cpus", "0"),
    "cpus negative": lambda a: _replace(a, "--cpus", "-1"),
    "no network": lambda a: _drop(a, "--network"),
    "network host": lambda a: _replace(a, "--network", "host"),
    "network HOST": lambda a: _replace(a, "--network", "HOST"),
    "network none": lambda a: _replace(a, "--network", "none"),
    "network bridge": lambda a: _replace(a, "--network", "bridge"),
    "network default": lambda a: _replace(a, "--network", "default"),
    "network container": lambda a: _replace(a, "--network", "container:other"),
    "privileged": lambda a: _insert_before_image(a, "--privileged"),
    "pid host": lambda a: _insert_before_image(a, "--pid", "host"),
    "pid=host": lambda a: _insert_before_image(a, "--pid=host"),
    "ipc host": lambda a: _insert_before_image(a, "--ipc", "host"),
    "uts host": lambda a: _insert_before_image(a, "--uts", "host"),
    "device": lambda a: _insert_before_image(a, "--device", "/dev/sda"),
    "volumes-from": lambda a: _insert_before_image(a, "--volumes-from", "other"),
    "unknown flag": lambda a: _insert_before_image(a, "--sysctl", "net.ipv4.ip_forward=1"),
    "user= spelling": lambda a: _insert_before_image(a, "--user=0"),
    "duplicate --user": lambda a: _insert_before_image(a, "--user", "0"),
    "docker socket": lambda a: _replace(a, "-v", "/var/run/docker.sock:/workspace:rw"),
    "docker socket as snap": lambda a: _set_mount(a, "/snap", "/var/run/docker.sock:/snap:rw"),
    "third mount": lambda a: _insert_before_image(a, "-v", "/tmp/extra:/extra:rw"),
    "one mount": lambda a: a[: _mount_index(a, "/snap") - 1] + a[_mount_index(a, "/snap") + 1 :],
    "wrong target": lambda a: _insert_before_image(_drop(a, "-v"), "-v", "/tmp/x:/etc:rw"),
    "relative mount source": lambda a: _replace(a, "-v", "ws:/workspace:rw"),
    "named volume": lambda a: _replace(a, "-v", "myvol:/workspace:rw"),
    "root mount": lambda a: _replace(a, "-v", "/:/workspace:rw"),
    "drive root mount": lambda a: _replace(a, "-v", "C:\\:/workspace:rw"),
    "drive root slash mount": lambda a: _replace(a, "-v", "D:/:/workspace:rw"),
    "home mount": lambda a: _replace(a, "-v", f"{Path.home()}:/workspace:rw"),
    "home parent mount": lambda a: _replace(a, "-v", f"{Path.home().parent}:/workspace:rw"),
    "dotdot mount": lambda a: _replace(a, "-v", "/srv/a/../../etc:/workspace:rw"),
    "etc mount": lambda a: _replace(a, "-v", "/etc:/workspace:rw"),
    "bad mount mode": lambda a: _replace(a, "-v", "/srv/ws:/workspace:rw,shared"),
    "mount propagation": lambda a: _replace(a, "-v", "/srv/ws:/workspace:rshared"),
    "nested mounts": lambda a: _set_mount(a, "/workspace", _mount_src(a, "/snap") + "/inner:/workspace:rw"),
    "api key with value": lambda a: [
        (f"ANTHROPIC_API_KEY={FAKE_KEY}" if t == "ANTHROPIC_API_KEY" else t) for t in a
    ],
    "other secret with value": lambda a: _insert_before_image(a, "-e", "GITHUB_TOKEN=abc"),
    "password with value": lambda a: _insert_before_image(a, "-e", "DB_PASSWORD=abc"),
    "bare non-allowlisted env": lambda a: _insert_before_image(a, "-e", "HOME"),
    "bare secret not allowlisted": lambda a: _insert_before_image(a, "-e", "AWS_SECRET_ACCESS_KEY"),
    "valued non-allowlisted env": lambda a: _insert_before_image(a, "-e", "FOO=bar"),
    "env-file": lambda a: _insert_before_image(a, "--env-file", "x.env"),
    "duplicate bare env": lambda a: _insert_before_image(a, "-e", "ANTHROPIC_API_KEY"),
    "arm env wrong": lambda a: [("ARCH_ARM=Z" if t == "ARCH_ARM=B" else t) for t in a],
    "arm env missing": lambda a: _drop_env(a, "ARCH_ARM="),
    "proxy env missing": lambda a: _drop_env(a, "HTTPS_PROXY="),
    "proxy not http": lambda a: [
        ("HTTPS_PROXY=ftp://egress:3128" if t.startswith("HTTPS_PROXY=") else t) for t in a
    ],
    "proxy userinfo": lambda a: [
        ("HTTPS_PROXY=http://u:p@egress:3128" if t.startswith("HTTPS_PROXY=") else t) for t in a
    ],
    "proxy no port": lambda a: [
        ("HTTPS_PROXY=http://egress" if t.startswith("HTTPS_PROXY=") else t) for t in a
    ],
    "proxy port range": lambda a: [
        ("HTTPS_PROXY=http://egress:99999" if t.startswith("HTTPS_PROXY=") else t) for t in a
    ],
    "tmpfs elsewhere": lambda a: _replace(a, "--tmpfs", "/etc:rw"),
    "tmpfs exec suid": lambda a: _replace(a, "--tmpfs", "/tmp:rw,suid"),
    "name injection": lambda a: _replace(a, "--name", "x --privileged"),
    "image whitespace": lambda a: [("img x" if t == "archstudy-agent:test" else t) for t in a],
    "empty image": lambda a: [("" if t == "archstudy-agent:test" else t) for t in a],
    "no image": lambda a: a[: a.index("archstudy-agent:test")],
    "not docker run": lambda a: ["podman", *a[1:]],
    "docker exec": lambda a: [a[0], "exec", *a[2:]],
    "newline in token": lambda a: _replace(a, "--name", "ok\n--privileged"),
    "flag missing value": lambda a: a[: a.index("--memory") + 1],
}


@pytest.mark.parametrize("label", sorted(MUTATIONS))
def test_mutation_is_refused(good, label):
    mutated = MUTATIONS[label](good)
    assert mutated != good, f"mutation {label!r} did not change the argv"
    with pytest.raises(IsolationError):
        validate_argv(mutated)


def test_key_with_a_value_is_refused_for_that_reason(good):
    mutated = MUTATIONS["api key with value"](good)
    assert f"ANTHROPIC_API_KEY={FAKE_KEY}" in mutated and mutated.count("ANTHROPIC_API_KEY") == 0
    with pytest.raises(IsolationError, match="by name only"):
        validate_argv(mutated)


def test_every_mutation_was_exercised_against_a_valid_baseline(good):
    validate_argv(good)
    assert len(MUTATIONS) >= 60


def test_non_list_and_non_string_argv_refused():
    for bad in (None, "docker run img", ["docker", "run", 5], [], ["docker"]):
        with pytest.raises(IsolationError):
            validate_argv(bad)


def test_key_value_never_appears_in_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    argv = launch(
        image="img:1",
        name="n",
        workspace=tmp_path / "w",
        snapshot_store=tmp_path / "s",
        network="net",
        proxy_url="http://p:3128",
        arm="A",
        command=["claude"],
    )
    assert FAKE_KEY not in str(argv)
    assert "sk-ant" not in str(argv)
    i = argv.index("ANTHROPIC_API_KEY")
    assert argv[i - 1] == "-e"  # passed by name only


def test_launch_returns_a_list_and_executes_nothing(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("launch() must not execute anything")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "call", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(os, "execvp", boom)
    argv = launch(
        image="img:1",
        name="n",
        workspace=tmp_path / "w",
        snapshot_store=tmp_path / "s",
        network="net",
        proxy_url="http://p:3128",
        arm="C",
        command=["claude"],
    )
    assert isinstance(argv, list) and argv[:2] == ["docker", "run"]


def test_launch_refuses_what_validate_refuses(tmp_path):
    with pytest.raises(IsolationError):
        launch(
            image="img x",
            name="n",
            workspace=tmp_path / "w",
            snapshot_store=tmp_path / "s",
            network="host",
            proxy_url="http://p:3128",
            arm="A",
            command=["claude"],
        )


def test_isolation_module_imports_nothing_that_can_execute_or_connect():
    tree = ast.parse((ROOT / "archstudy" / "isolation.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported <= {"__future__", "re", "collections.abc", "pathlib", "typing"}, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"os", "subprocess", "socket", "open", "eval", "exec"}


# -- static checks of the image recipe (no Docker needed) -----------------------------------------

PINNED = ("CLAUDE_CODE_VERSION", "REDIS_VERSION", "REQUESTS_VERSION", "PYTEST_VERSION")


def _dockerfile_lines() -> list[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    joined = re.sub(r"\\\r?\n", " ", text)
    return [ln.strip() for ln in joined.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_dockerfile_final_user_is_numeric_and_not_root():
    users = [ln.split(None, 1)[1] for ln in _dockerfile_lines() if ln.upper().startswith("USER ")]
    assert users, "no USER instruction"
    match = re.fullmatch(r"(\d+)(?::(\d+))?", users[-1])
    assert match, users[-1]
    assert int(match.group(1)) != 0 and int(match.group(2) or 1) != 0
    assert _dockerfile_lines()[-1].upper().startswith("USER "), "USER must be the last instruction"


def test_dockerfile_has_no_key_no_remote_add_no_entrypoint():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in text
    assert "sk-ant" not in text
    lines = _dockerfile_lines()
    assert not any(re.match(r"ADD\s+https?://", ln, re.IGNORECASE) for ln in lines)
    assert not any(ln.upper().startswith("ENTRYPOINT") for ln in lines)
    assert not any(re.match(r"ENV\b.*(KEY|TOKEN|SECRET|PASSWORD)", ln, re.IGNORECASE) for ln in lines)
    assert text.isascii()


def test_dockerfile_pinned_args_have_no_default_and_are_checked_non_empty():
    lines = _dockerfile_lines()
    for name in PINNED:
        arg_lines = [ln for ln in lines if re.fullmatch(rf"ARG\s+{name}(=.*)?", ln)]
        assert len(arg_lines) == 1, name
        assert "=" not in arg_lines[0], f"{name} must have no default"
        checks = [ln for ln in lines if ln.startswith("RUN") and f'"{name}=${{{name}}}"' in ln]
        assert checks, f"{name} is never checked"
        assert '[ -z "${value}" ]' in checks[0] and "exit 1" in checks[0]


def test_dockerfile_base_installs_and_layout():
    lines = _dockerfile_lines()
    assert lines[0] == "ARG PYTHON_IMAGE=python:3.12-slim"
    assert lines[1] == "FROM ${PYTHON_IMAGE}"
    text = "\n".join(lines)
    assert "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" in text
    assert "redis==${REDIS_VERSION}" in text and "requests==${REQUESTS_VERSION}" in text
    assert "pytest==${PYTEST_VERSION}" in text
    assert "--no-cache-dir" in text
    assert "nodejs" in text and "npm" in text
    assert "--uid 10001" in text and "nologin" in text
    assert "COPY archstudy/codebase/docs/adr/ /opt/archstudy/codebase/docs/adr/" in text
    assert "COPY archstudy/container/managed-settings.json /etc/claude-code/managed-settings.json" in text
    assert "chmod 0444 /etc/claude-code/managed-settings.json" in text
    assert "chmod 0555 /etc/claude-code" in text
    assert "chown -R root:root /opt/archstudy" in text
    assert "WORKDIR /workspace" in lines


def _copied_archstudy_files():
    files = []
    for ln in _dockerfile_lines():
        if ln.startswith("COPY archstudy/") and ln.rstrip().endswith("/opt/archstudy/"):
            files += [tok for tok in ln.split()[1:-1] if tok.startswith("archstudy/")]
    return files


SCORER_SIDE = ("heldout", "score", "tasks", "solutions", "standin", "dryrun", "workspace", "isolation",
               "egress", "redaction", "acceptance")


def test_the_image_copies_an_allowlist_never_the_whole_package():
    text = "\n".join(_dockerfile_lines())
    assert "COPY archstudy/ /opt/archstudy/" not in text and "COPY . " not in text
    copied = _copied_archstudy_files()
    assert copied, "no archstudy files are copied"
    for name in SCORER_SIDE:
        assert not any(name in f for f in copied), f"{name} must not be copied into the agent's image"
    assert not any("acceptance" in ln for ln in _dockerfile_lines() if ln.startswith("COPY"))


def test_the_image_contains_exactly_what_the_hook_and_the_commit_check_import():
    import ast

    root = ARCH_DIR
    needed, todo = set(), ["hook", "precommit"]
    while todo:
        name = todo.pop()
        if name in needed:
            continue
        needed.add(name)
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "archstudy":
                # heldout is imported behind an ImportError guard in rules.py and is
                # deliberately absent from the image
                todo += [a.name for a in node.names
                         if (root / f"{a.name}.py").exists() and a.name != "heldout"]
    copied = {Path(f).stem for f in _copied_archstudy_files()}
    assert needed <= copied | {"__init__"}, f"missing from the image: {needed - copied}"
    assert copied - {"__init__"} <= needed, f"copied but not needed by the hook: {copied - needed}"


def test_managed_settings_enforce_the_hook():
    settings = json.loads(MANAGED.read_text(encoding="utf-8"))
    assert settings["allowManagedHooksOnly"] is True
    assert settings["disableAllHooks"] is False
    entries = settings["hooks"]["PostToolUse"]
    assert len(entries) == 1 and entries[0]["matcher"] == "*"
    (hook,) = entries[0]["hooks"]
    assert hook["type"] == "command" and hook["command"].startswith("python /opt/archstudy/")
    assert hook["timeout"] == 30


# -- daemon test: meaningful when Docker runs, skipped otherwise -----------------------------------

BASE_IMAGE = "python:3.12-slim"
_DAEMON = _docker_ok("info") and _image_present(BASE_IMAGE)


@pytest.mark.skipif(not _DAEMON, reason="Docker daemon not running or python:3.12-slim not present locally")
def test_hardened_container_runs_as_uid_10001_with_read_only_root():
    base = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        BASE_IMAGE,
        "python",
        "-c",
    ]
    uid = subprocess.run([*base, "import os;print(os.getuid())"], capture_output=True, text=True, timeout=60)
    assert uid.returncode == 0 and uid.stdout.strip() == "10001", uid.stderr
    write = subprocess.run(
        [*base, "open('/probe','w').write('x')"], capture_output=True, text=True, timeout=60
    )
    assert write.returncode != 0
    assert "Read-only" in write.stderr or "Permission denied" in write.stderr
