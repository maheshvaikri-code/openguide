"""Container isolation for the agent session: a pure argv builder and a fail-closed validator.

Step 1 of the architecture-drift study never starts a session. ``launch`` builds an argv, validates it
and RETURNS it; nothing here executes a process, opens a socket or reads a secret. The validator is an
allowlist: every flag, mount and environment entry must be explicitly permitted, anything else is
refused with ``IsolationError``.

The API key is passed to the container by NAME only (``-e ANTHROPIC_API_KEY``), so the value is read by
the Docker client from the launcher's environment and never appears in argv, logs or this module.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

__all__ = ["IsolationError", "docker_run_argv", "validate_argv", "launch"]


class IsolationError(Exception):
    """The container launch specification is unsafe or malformed (fail closed)."""


ARMS = ("A", "B", "C")
DEFAULT_ENV_NAMES = ("ANTHROPIC_API_KEY",)

# Environment entries: bare names are passed through by name (value never in argv); valued entries
# are the only two the harness sets itself.
ALLOWED_BARE_ENV = frozenset({"ANTHROPIC_API_KEY"})
ALLOWED_VALUED_ENV = frozenset({"ARCH_ARM", "HTTPS_PROXY"})
_SECRETISH = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)

# Flag allowlist. Anything not listed here (--privileged, --cap-add, --device, --pid, --ipc, --uts,
# --volumes-from, --mount, --env-file, --publish, --add-host, --security-opt variants, and every
# "--flag=value" spelling) is refused.
FLAGS_NO_VALUE = frozenset({"--rm", "--read-only"})
FLAGS_WITH_VALUE = frozenset(
    {
        "--name",
        "--user",
        "--tmpfs",
        "--cap-drop",
        "--security-opt",
        "--pids-limit",
        "--memory",
        "--cpus",
        "--network",
        "-v",
        "-e",
    }
)
REPEATABLE_FLAGS = frozenset({"-v", "-e"})
REQUIRED_FLAGS = (
    "--user",
    "--read-only",
    "--cap-drop",
    "--security-opt",
    "--pids-limit",
    "--memory",
    "--cpus",
    "--network",
)
MOUNT_TARGETS = frozenset({"/workspace", "/snap"})

_FORBIDDEN_NETWORKS = frozenset({"host", "none", "bridge", "default", ""})
_UNSAFE_POSIX_PREFIXES = ("etc", "proc", "sys", "dev", "boot", "run", "var/run")
_DRIVE_ABS = re.compile(r"^[A-Za-z]:[\\/]")
_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]*$")
_MOUNT = re.compile(r"^(?P<src>.+):(?P<dst>/[^:]*):(?P<mode>rw|ro)$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_USER = re.compile(r"^([0-9]{1,10})(?::([0-9]{1,10}))?$")
_MEMORY = re.compile(r"^[1-9][0-9]*[bkmg]?$", re.IGNORECASE)
_CPUS = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$")
_PROXY = re.compile(r"^http://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?:([0-9]{1,5})$")
_TMPFS_OPTS = re.compile(r"^(?:rw|nosuid|nodev|noexec|size=[1-9][0-9]*[kmg])$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def docker_run_argv(
    *,
    image: str,
    name: str,
    workspace: Path,
    snapshot_store: Path,
    network: str,
    proxy_url: str,
    arm: str,
    env_names: Sequence[str] = DEFAULT_ENV_NAMES,
    memory: str = "2g",
    cpus: str = "2",
    pids: int = 256,
    command: Sequence[str],
) -> list[str]:
    """Build the ``docker run`` argv for one agent session. Pure: no I/O, no environment reads.

    Secrets in ``env_names`` are passed by name only. The result is NOT validated here; ``launch``
    (or the caller) must pass it through ``validate_argv`` before use.
    """
    if arm not in ARMS:
        raise IsolationError(f"arm must be one of {ARMS}, got {arm!r}")
    for label, path in (("workspace", workspace), ("snapshot_store", snapshot_store)):
        if not Path(path).is_absolute():
            raise IsolationError(f"{label} mount path must be absolute: {str(path)!r}")
    for env_name in env_names:
        if not isinstance(env_name, str) or not _ENV_NAME.match(env_name):
            raise IsolationError(f"env name must be a bare identifier (no '='): {env_name!r}")
    argv = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--user",
        "10001:10001",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,size=512m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(pids),
        "--memory",
        memory,
        "--cpus",
        cpus,
        "--network",
        network,
        "-v",
        f"{workspace}:/workspace:rw",
        "-v",
        f"{snapshot_store}:/snap:rw",
        "-e",
        f"HTTPS_PROXY={proxy_url}",
        "-e",
        f"ARCH_ARM={arm}",
    ]
    for env_name in env_names:
        argv += ["-e", env_name]
    argv.append(image)
    argv.extend(command)
    return argv


def _parse(argv: Sequence[str]) -> tuple[dict[str, list[str]], str, list[str]]:
    """Split argv into allowlisted flags, the image and the in-container command."""
    if not isinstance(argv, (list, tuple)) or not all(isinstance(t, str) for t in argv):
        raise IsolationError("argv must be a list of strings")
    for token in argv:
        if _CONTROL.search(token):
            raise IsolationError("argv contains a control character")
    if len(argv) < 3 or list(argv[:2]) != ["docker", "run"]:
        raise IsolationError("argv must start with 'docker run' and contain an image")
    flags: dict[str, list[str]] = {}
    i = 2
    while i < len(argv):
        token = argv[i]
        if not token.startswith("-"):
            break
        if token in FLAGS_NO_VALUE:
            value = ""
            i += 1
        elif token in FLAGS_WITH_VALUE:
            if i + 1 >= len(argv):
                raise IsolationError(f"flag {token} is missing its value")
            value = argv[i + 1]
            i += 2
        else:
            raise IsolationError(f"flag not allowed: {token}")
        if token in flags and token not in REPEATABLE_FLAGS:
            raise IsolationError(f"flag given more than once: {token}")
        flags.setdefault(token, []).append(value)
    if i >= len(argv):
        raise IsolationError("image is missing")
    return flags, argv[i], list(argv[i + 1 :])


def _components(path: str) -> list[str]:
    """Normalised path components: forward slashes, no empties, case-folded for drive paths."""
    norm = path.replace("\\", "/")
    if _DRIVE_ABS.match(path):
        norm = norm.lower()
    return [part for part in norm.split("/") if part]


def _check_user(value: str) -> None:
    match = _USER.match(value)
    if not match:
        raise IsolationError(f"--user must be a numeric uid[:gid], got {value!r}")
    if int(match.group(1)) == 0 or (match.group(2) is not None and int(match.group(2)) == 0):
        raise IsolationError("--user must not be root (uid 0 or gid 0)")


def _check_limits(flags: dict[str, list[str]]) -> None:
    pids = flags["--pids-limit"][0]
    if not pids.isascii() or not pids.isdigit() or int(pids) <= 0:
        raise IsolationError(f"--pids-limit must be a positive integer, got {pids!r}")
    memory = flags["--memory"][0]
    if not _MEMORY.match(memory):
        raise IsolationError(f"--memory must be a positive size, got {memory!r}")
    cpus = flags["--cpus"][0]
    if not _CPUS.match(cpus) or float(cpus) <= 0:
        raise IsolationError(f"--cpus must be a positive number, got {cpus!r}")


def _check_network(value: str) -> None:
    lowered = value.lower()
    if lowered in _FORBIDDEN_NETWORKS or lowered.startswith("container:"):
        raise IsolationError(f"--network {value!r} is not allowed (need a dedicated internal network)")
    if not _NAME.match(value):
        raise IsolationError(f"--network name is malformed: {value!r}")


def _check_tmpfs(value: str) -> None:
    target, _, opts = value.partition(":")
    if target != "/tmp":
        raise IsolationError(f"--tmpfs target must be /tmp, got {target!r}")
    for opt in filter(None, opts.split(",")):
        if not _TMPFS_OPTS.match(opt):
            raise IsolationError(f"--tmpfs option not allowed: {opt!r}")


def _check_mounts(mounts: list[str]) -> None:
    if len(mounts) != 2:
        raise IsolationError(f"exactly two -v mounts are required, got {len(mounts)}")
    home = _components(str(Path.home()))
    sources: list[list[str]] = []
    targets: list[str] = []
    for spec in mounts:
        match = _MOUNT.match(spec)
        if not match:
            raise IsolationError(f"-v mount is malformed (want ABS_SRC:/target:rw|ro): {spec!r}")
        src, dst = match.group("src"), match.group("dst")
        if not (_DRIVE_ABS.match(src) or src.startswith("/")):
            raise IsolationError(f"-v source must be an absolute path: {src!r}")
        lowered = src.lower()
        if "docker.sock" in lowered or "docker_engine" in lowered:
            raise IsolationError("mounting the Docker socket is forbidden")
        if _DRIVE_ROOT.match(src):
            raise IsolationError(f"-v source must not be a drive root: {src!r}")
        parts = _components(src)
        if ".." in parts:
            raise IsolationError(f"-v source must not contain '..': {src!r}")
        if not parts or parts == home[: len(parts)]:
            raise IsolationError(
                f"-v source must not be the filesystem root, the home dir or its parent: {src!r}"
            )
        joined = "/".join(parts)
        if src.startswith("/") and any(
            joined == p or joined.startswith(p + "/") for p in _UNSAFE_POSIX_PREFIXES
        ):
            raise IsolationError(f"-v source is a protected system path: {src!r}")
        sources.append(parts)
        targets.append(dst)
    if sorted(targets) != sorted(MOUNT_TARGETS):
        raise IsolationError(f"mount targets must be exactly {sorted(MOUNT_TARGETS)}, got {sorted(targets)}")
    first, second = sources
    if first[: len(second)] == second or second[: len(first)] == first:
        raise IsolationError("the workspace and snapshot sources must not contain one another")


def _check_env(entries: list[str]) -> None:
    seen: set[str] = set()
    valued: dict[str, str] = {}
    for entry in entries:
        name, eq, value = entry.partition("=")
        if not _ENV_NAME.match(name):
            raise IsolationError(f"-e entry is malformed: {name!r}")
        if name in seen:
            raise IsolationError(f"-e {name} given more than once")
        seen.add(name)
        if eq:
            if _SECRETISH.search(name):
                raise IsolationError(f"-e {name} carries a value; secrets must be passed by name only")
            if "sk-ant-" in value:
                raise IsolationError(f"-e {name} value looks like an API key")
            if name not in ALLOWED_VALUED_ENV:
                raise IsolationError(f"-e {name}=... is not in the allowlist")
            valued[name] = value
        elif name not in ALLOWED_BARE_ENV:
            raise IsolationError(f"-e {name} is not in the allowlist")
    if valued.get("ARCH_ARM") not in ARMS:
        raise IsolationError("ARCH_ARM must be set to one of A, B, C")
    proxy = _PROXY.match(valued.get("HTTPS_PROXY", ""))
    if not proxy or not 1 <= int(proxy.group(1)) <= 65535:
        raise IsolationError("HTTPS_PROXY must be set to an http://host:port URL")


def validate_argv(argv: Sequence[str]) -> None:
    """Raise ``IsolationError`` unless ``argv`` satisfies every hardening property. Fail closed."""
    flags, image, _command = _parse(argv)
    for required in REQUIRED_FLAGS:
        if required not in flags:
            raise IsolationError(f"required flag missing: {required}")
    _check_user(flags["--user"][0])
    if flags["--cap-drop"][0] != "ALL":
        raise IsolationError("--cap-drop must be exactly ALL")
    if flags["--security-opt"][0] != "no-new-privileges":
        raise IsolationError("--security-opt must be exactly no-new-privileges")
    _check_limits(flags)
    _check_network(flags["--network"][0])
    if "--tmpfs" in flags:
        _check_tmpfs(flags["--tmpfs"][0])
    if "--name" in flags and not _NAME.match(flags["--name"][0]):
        raise IsolationError(f"--name is malformed: {flags['--name'][0]!r}")
    _check_mounts(flags.get("-v", []))
    _check_env(flags.get("-e", []))
    if not image or re.search(r"\s", image):
        raise IsolationError(f"image must be non-empty and contain no whitespace: {image!r}")


def launch(**kwargs: Any) -> list[str]:
    """Build the argv with ``docker_run_argv(**kwargs)``, validate it, and RETURN it.

    Step 1 of the study never starts a session: this function executes nothing, opens no connection
    and reads no secret. Starting the container is a later, separately approved step.
    """
    argv = docker_run_argv(**kwargs)
    validate_argv(argv)
    return argv
