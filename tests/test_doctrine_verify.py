"""Tests for tools/doctrine_verify.py — source-vs-consumer gate scoping.

Regression for the ADR-002 defect: in a consumer repo (a host repo with
its own code), doctrine_verify must NOT ruff the host's files or run the
host's test suite; it verifies only Doctrine's own surface (lint + state).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import doctrine_verify as dv  # noqa: E402


class TestSourceDetection(unittest.TestCase):
    def test_doctrineos_pyproject_is_source(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text(
                '[project]\nname = "doctrineos"\n', encoding="utf-8")
            self.assertTrue(dv.is_source_repo(Path(d)))

    def test_no_pyproject_is_consumer(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(dv.is_source_repo(Path(d)))

    def test_other_pyproject_is_consumer(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text(
                '[project]\nname = "maple-oss"\n', encoding="utf-8")
            self.assertFalse(dv.is_source_repo(Path(d)))


class TestGateScoping(unittest.TestCase):
    def _run(self, root: Path):
        ran: list[str] = []

        def fake_gate(name, cmd, cwd):
            ran.append(name)
            return True

        with mock.patch.object(dv, "run_gate", fake_gate):
            rc = dv.main([str(root)])
        return rc, ran

    def test_consumer_runs_only_doctrine_surface(self):
        # no pyproject => consumer; no state plane => state skipped.
        with tempfile.TemporaryDirectory() as d:
            rc, ran = self._run(Path(d))
        self.assertEqual(rc, 0)
        self.assertEqual(ran, ["lint"])  # NOT ruff, NOT the host test suite

    def test_consumer_still_verifies_state_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / ".doctrine-state"
            sp.mkdir()
            (sp / "checkpoint.json").write_text("{}", encoding="utf-8")
            rc, ran = self._run(Path(d))
        self.assertEqual(ran, ["lint", "state"])
        self.assertNotIn("tests", ran)

    def test_source_runs_full_suite(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pyproject.toml").write_text(
                '[project]\nname = "doctrineos"\n', encoding="utf-8")
            rc, ran = self._run(Path(d))
        self.assertIn("lint", ran)
        self.assertIn("tests", ran)  # the doctrine dev suite runs in source


if __name__ == "__main__":
    unittest.main()
