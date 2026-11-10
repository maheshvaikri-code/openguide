"""Secret hygiene for the study harness: redact key-shaped strings and scan files for them.

``redact`` is applied to every string the harness stores (traces, logs, snapshots metadata).
``find_secrets`` reports WHERE a secret-shaped string is (path, line, rule name) and never the text.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = ["REDACTED", "redact", "find_secrets", "MAX_SCAN_BYTES"]

REDACTED = "[REDACTED]"
MAX_SCAN_BYTES = 2 * 1024 * 1024
_BINARY_SNIFF = 8192

_KEY = re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")
# Header and assignment rules keep the label (group 1) and replace the value (group 2).
# A value stops at whitespace, a quote or a backslash (so an escaped newline in a JSON log ends it).
_BEARER = re.compile(r"(authorization\s*:\s*bearer\s+)([^\s\"'\\]+)", re.IGNORECASE)
_X_API_KEY = re.compile(r"(x-api-key\s*:\s*)([^\s\"'\\]+)", re.IGNORECASE)
_ENV_ASSIGN = re.compile(r"(ANTHROPIC_API_KEY\s*=\s*[\"']?)([^\s\"'\\]+)")

# name, pattern, is_labelled (value must be checked against placeholders when scanning)
_RULES: tuple[tuple[str, re.Pattern[str], bool], ...] = (
    ("anthropic-key", _KEY, False),
    ("bearer-header", _BEARER, True),
    ("x-api-key-header", _X_API_KEY, True),
    ("anthropic-env-assignment", _ENV_ASSIGN, True),
)

# A labelled value that is obviously not a secret: documentation placeholders and already-redacted text.
_PLACEHOLDER = re.compile(
    r"^(?:\[REDACTED\]|<.*|\$\S*|\{[^}]*\}|\*+|x+|\.{3}|your[-_].*|token)$", re.IGNORECASE
)


def redact(text: str) -> str:
    """Replace key-shaped strings and credential header/assignment values with ``[REDACTED]``."""
    if not isinstance(text, str):
        raise TypeError(f"redact() needs a str, got {type(text).__name__}")
    for _name, pattern, labelled in _RULES:
        if labelled:
            text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def _iter_files(paths: Iterable[Path]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            # Unreadable subdirectories are skipped by os.walk; an explicitly named file is not.
            for root, dirs, files in os.walk(path):
                dirs.sort()
                for name in sorted(files):
                    yield Path(root) / name
        else:
            yield path


def _read_text(path: Path) -> str | None:
    """Return the file's text, or None for files that are too large or binary."""
    if path.stat().st_size > MAX_SCAN_BYTES:
        return None
    data = path.read_bytes()
    if b"\x00" in data[:_BINARY_SNIFF]:
        return None
    return data.decode("utf-8", errors="replace")


def find_secrets(paths: Iterable[Path]) -> list[tuple[Path, int, str]]:
    """Return (path, line number, rule name) for every secret-shaped string; never the string itself.

    Directories are walked recursively. Files over 2 MiB and binary files are skipped.
    """
    findings: list[tuple[Path, int, str]] = []
    for path in _iter_files(paths):
        text = _read_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.split("\n"), start=1):
            for name, pattern, labelled in _RULES:
                for match in pattern.finditer(line):
                    if labelled and _PLACEHOLDER.match(match.group(2)):
                        continue
                    findings.append((path, number, name))
    return findings
