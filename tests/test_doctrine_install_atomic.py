"""Regression: an update over an existing Doctrine requires --force (atomic).

A non-force install into a repo that already has `.Doctrine.md` would copy new
framework files but skip changed ones, drifting the README counts + installer
manifest and leaving the consumer's framework internally inconsistent (its own
doctrine_lint / doctrine_packaging then fail — the OpenHawk drift, 2026-07-16).
The installer must refuse a non-force update, and never touch the target.
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import doctrine_install as di  # noqa: E402


class TestAtomicUpdate(unittest.TestCase):
    def test_update_without_force_is_refused_and_touches_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "consumer"
            target.mkdir()
            (target / ".Doctrine.md").write_text("# stale doctrine\n", "utf-8")
            rc = di.install(REPO, target, ["claude"],
                            enterprise=False, ci=False, force=False)
            self.assertEqual(rc, 2)  # refused before any copy
            # the partial update never happened — the stale marker is untouched,
            # and no new framework dirs were created
            self.assertEqual((target / ".Doctrine.md").read_text("utf-8"),
                             "# stale doctrine\n")
            self.assertFalse((target / ".Doctrine").exists())

    def test_update_with_force_proceeds(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "consumer"
            target.mkdir()
            (target / ".Doctrine.md").write_text("# stale doctrine\n", "utf-8")
            rc = di.install(REPO, target, ["claude"],
                            enterprise=False, ci=False, force=True)
            self.assertIn(rc, (0, 1))  # proceeds; --force overwrites atomically
            self.assertNotEqual((target / ".Doctrine.md").read_text("utf-8"),
                                "# stale doctrine\n")  # real law synced in

    def test_fresh_install_without_force_still_works(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "fresh"
            rc = di.install(REPO, target, ["claude"],
                            enterprise=False, ci=False, force=False)
            self.assertIn(rc, (0, 1))  # fresh (no existing .Doctrine.md) is fine
            self.assertTrue((target / ".Doctrine.md").exists())


if __name__ == "__main__":
    unittest.main()
