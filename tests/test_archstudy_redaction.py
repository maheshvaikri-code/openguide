"""WP7 / AC 8: key-shaped strings are redacted from anything stored, and a scan finds none in the repo.

Key-shaped fixtures are assembled at runtime so no such literal exists in any file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from archstudy.redaction import MAX_SCAN_BYTES, REDACTED, find_secrets, redact

ROOT = Path(__file__).resolve().parent.parent
KEY = "sk-" + "ant-" + "api03-" + "AbC_dEf-123456789"
SHORT = "sk-" + "ant-" + "short"  # fewer than 10 chars after the prefix: not key-shaped
TOKEN = "tok" + "en" + "VALUE123456"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"key is {KEY} ok", f"key is {REDACTED} ok"),
        (KEY, REDACTED),
        (f"a {KEY} b {KEY} c", f"a {REDACTED} b {REDACTED} c"),
        (f"Authorization: Bearer {TOKEN}", f"Authorization: Bearer {REDACTED}"),
        (f"authorization:bearer {TOKEN}", f"authorization:bearer {REDACTED}"),
        (f"AUTHORIZATION: BEARER {TOKEN}", f"AUTHORIZATION: BEARER {REDACTED}"),
        (f"x-api-key: {TOKEN}", f"x-api-key: {REDACTED}"),
        (f"X-API-KEY:{TOKEN}", f"X-API-KEY:{REDACTED}"),
        (f"ANTHROPIC_API_KEY={TOKEN}", f"ANTHROPIC_API_KEY={REDACTED}"),
        (f"ANTHROPIC_API_KEY = {TOKEN}", f"ANTHROPIC_API_KEY = {REDACTED}"),
        (f'ANTHROPIC_API_KEY="{TOKEN}"', f'ANTHROPIC_API_KEY="{REDACTED}"'),
        (f"export ANTHROPIC_API_KEY={KEY}", f"export ANTHROPIC_API_KEY={REDACTED}"),
        (f"curl -H 'x-api-key: {KEY}' https://x", f"curl -H 'x-api-key: {REDACTED}' https://x"),
        (f"line1\nAuthorization: Bearer {TOKEN}\nline3", f"line1\nAuthorization: Bearer {REDACTED}\nline3"),
        (
            '{"h": "Authorization: Bearer ' + TOKEN + '\\nnext"}',
            '{"h": "Authorization: Bearer ' + REDACTED + '\\nnext"}',
        ),
        ("", ""),
        ("nothing to see here", "nothing to see here"),
        (SHORT, SHORT),
        ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),  # a bare name carries no value
        ("-e ANTHROPIC_API_KEY image", "-e ANTHROPIC_API_KEY image"),
        ("Authorization: Basic abc", "Authorization: Basic abc"),
    ],
)
def test_redact_table(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize(
    "sample", [KEY, f"Authorization: Bearer {TOKEN}", f"x-api-key: {KEY} ANTHROPIC_API_KEY={TOKEN}"]
)
def test_redact_is_idempotent_and_removes_the_secret(sample):
    once = redact(sample)
    assert redact(once) == once
    assert KEY not in once and TOKEN not in once


@pytest.mark.parametrize("bad", [None, 5, b"bytes", ["x"], {"a": 1}])
def test_redact_rejects_non_str(bad):
    with pytest.raises(TypeError):
        redact(bad)


def test_find_secrets_reports_location_and_rule_never_the_secret(tmp_path):
    leaky = tmp_path / "leaky.txt"
    leaky.write_text(
        f"clean line\nstored {KEY} here\nx-api-key: {TOKEN}\nAuthorization: Bearer {TOKEN}\n"
        f"ANTHROPIC_API_KEY={TOKEN}\n",
        encoding="utf-8",
    )
    findings = find_secrets([leaky])
    assert findings == [
        (leaky, 2, "anthropic-key"),
        (leaky, 3, "x-api-key-header"),
        (leaky, 4, "bearer-header"),
        (leaky, 5, "anthropic-env-assignment"),
    ]
    flat = repr(findings)
    assert KEY not in flat and TOKEN not in flat and "sk-ant" not in flat


def test_find_secrets_ignores_placeholders_and_redacted_text(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text(
        "ANTHROPIC_API_KEY=<your key>\nAuthorization: Bearer <token>\nx-api-key: [REDACTED]\n"
        "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}\nANTHROPIC_API_KEY={key}\n" + SHORT + "\n",
        encoding="utf-8",
    )
    assert find_secrets([doc]) == []


def test_find_secrets_skips_binary_and_huge_files_and_tolerates_bad_utf8(tmp_path):
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01" + KEY.encode())
    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"a" * MAX_SCAN_BYTES + b"\n" + KEY.encode())
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe junk\n" + KEY.encode())
    assert find_secrets([binary, huge]) == []
    assert find_secrets([bad]) == [(bad, 2, "anthropic-key")]


def test_find_secrets_walks_directories_in_a_stable_order(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "a.txt").write_text(KEY, encoding="utf-8")
    (tmp_path / "b" / "c.txt").write_text("ok\n" + KEY, encoding="utf-8")
    assert find_secrets([tmp_path]) == [
        (tmp_path / "a.txt", 1, "anthropic-key"),
        (tmp_path / "b" / "c.txt", 2, "anthropic-key"),
    ]


def test_find_secrets_fails_loudly_on_a_missing_named_file(tmp_path):
    with pytest.raises(OSError):
        find_secrets([tmp_path / "does-not-exist.txt"])


def test_the_repository_contains_no_key_shaped_strings():
    roots = [ROOT / "archstudy", ROOT / "docs", ROOT / "scripts"]
    assert all(r.is_dir() for r in roots), [str(r) for r in roots if not r.is_dir()]
    own_tests = sorted((ROOT / "tests").glob("test_archstudy_*.py"))
    findings = find_secrets([*roots, *own_tests])
    assert findings == [], [(str(p.relative_to(ROOT)), n, rule) for p, n, rule in findings]
