"""Tests for tools/doctrine_lint.py — run: python -m unittest discover tests"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import doctrine_lint as dl  # noqa: E402


class TestCorpusClean(unittest.TestCase):
    def test_current_corpus_passes(self):
        self.assertEqual(dl.main([str(REPO)]), 0)


class TestVersionCarrierScope(unittest.TestCase):
    """A consumer repo's own pyproject version is not a Doctrine desync."""

    def _doc(self, root: Path, version: str) -> None:
        (root / ".Doctrine.md").write_text(
            f"# .Doctrine.md - Engineering Doctrine v{version}\n", encoding="utf-8")

    def test_consumer_pyproject_not_a_carrier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._doc(root, "0.6.16")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "openhawk"\nversion = "0.1.0"\n',
                encoding="utf-8")
            findings: list[str] = []
            dl.check_version(root, findings)
            self.assertEqual(
                [f for f in findings if "pyproject" in f], [],
                f"consumer pyproject wrongly flagged: {findings}")

    def test_doctrineos_pyproject_desync_still_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._doc(root, "0.6.16")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "doctrineos"\nversion = "0.6.15"\n',
                encoding="utf-8")
            findings: list[str] = []
            dl.check_version(root, findings)
            self.assertTrue(
                any("pyproject" in f for f in findings),
                "doctrineos pyproject desync should be caught")

    def test_consumer_changelog_not_a_carrier(self):
        # a consumer repo's own CHANGELOG (its product version) is not a desync
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._doc(root, "0.6.17")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "openhawk"\nversion = "0.2.0"\n',
                encoding="utf-8")
            (root / "CHANGELOG.md").write_text(
                "# Changelog\n\n## [0.2.0] - 2026-07-14\n", encoding="utf-8")
            findings: list[str] = []
            dl.check_version(root, findings)
            self.assertEqual(
                [f for f in findings if "CHANGELOG" in f], [],
                f"consumer CHANGELOG wrongly flagged: {findings}")

    def test_source_changelog_desync_still_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._doc(root, "0.6.17")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "doctrineos"\nversion = "0.6.17"\n',
                encoding="utf-8")
            (root / "CHANGELOG.md").write_text(
                "# Changelog\n\n## [0.6.16] - 2026-07-14\n", encoding="utf-8")
            findings: list[str] = []
            dl.check_version(root, findings)
            self.assertTrue(
                any("CHANGELOG" in f for f in findings),
                "source CHANGELOG desync should be caught")


class TestBrokenRefCaught(unittest.TestCase):
    def test_broken_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".Doctrine").mkdir()
            (root / ".claude" / "agents").mkdir(parents=True)
            (root / ".Doctrine.md").write_text(
                "see `skills/does-not-exist.md`\n", encoding="utf-8")
            findings: list[str] = []
            dl.check_references(root, findings)
            self.assertEqual(len(findings), 1)
            self.assertIn("does-not-exist", findings[0])

    def test_allowlisted_external_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".Doctrine").mkdir()
            (root / ".claude" / "agents").mkdir(parents=True)
            (root / ".Doctrine.md").write_text(
                "upstream `skills/ponytail/SKILL.md`\n", encoding="utf-8")
            findings: list[str] = []
            dl.check_references(root, findings)
            self.assertEqual(findings, [])


class TestVersionSync(unittest.TestCase):
    def test_desync_caught(self):
        # In Doctrine's SOURCE repo (doctrineos pyproject), a CHANGELOG that
        # lags the header is a desync. The pyproject matches the header so the
        # CHANGELOG is the only finding. (Consumer repos are covered by
        # TestVersionCarrierScope - there this same shape is NOT flagged.)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".Doctrine.md").write_text(
                "# Doctrine v9.9.9\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "doctrineos"\nversion = "9.9.9"\n',
                encoding="utf-8")
            (root / "CHANGELOG.md").write_text(
                "# Changelog\n\n## [0.1.0] - 2026-01-01\n",
                encoding="utf-8")
            findings: list[str] = []
            dl.check_version(root, findings)
            self.assertEqual(len(findings), 1)
            self.assertIn("desync", findings[0])


if __name__ == "__main__":
    unittest.main()
