"""Tests for tools/doctrine_signature.py — run: python -m unittest discover tests

The Signature block is a GENERATED artifact: derived from the corpus's primary
sources (role Loads lines, .claude/agents cards, the inverse used-by map) and
lint-enforced so it can never drift. These tests pin the three properties that
make "generated + enforced" trustworthy: determinism, marker-scoped splicing
(hand-written prose is never touched), and drift detection.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import doctrine_signature as ds  # noqa: E402


class TestLiveCorpus(unittest.TestCase):
    """The committed corpus must already be fully signed and current."""

    def test_every_signature_current(self):
        findings: list[str] = []
        ds.check(REPO, findings)
        self.assertEqual(findings, [],
                         "run: python tools/doctrine_signature.py --write")

    def test_write_is_idempotent(self):
        # A no-op --write on the live tree writes zero blocks (already current).
        # We re-derive and confirm each committed block equals the regenerated
        # one, which is exactly what a 0-write run asserts.
        for path, block in ds._disciplines(REPO):
            self.assertEqual(ds._current_block(path.read_text("utf-8")), block,
                             f"{path.name}: committed block != regenerated")


class TestDeterminism(unittest.TestCase):
    def test_render_is_stable_across_calls(self):
        rsm = ds.role_skill_map(REPO)
        a = ds.render(ds.role_signature(REPO, "backend-engineer",
                                        rsm["backend-engineer"]))
        b = ds.render(ds.role_signature(REPO, "backend-engineer",
                                        rsm["backend-engineer"]))
        self.assertEqual(a, b)

    def test_skills_are_sorted(self):
        # Order must not depend on parse/insertion order.
        sig = ds.role_signature(REPO, "backend-engineer",
                                ["testing", "backend", "performance"])
        # role_signature formats whatever list it is handed; the corpus map
        # sorts, so assert the map output is sorted for a multi-skill role.
        skills = ds.role_skill_map(REPO)["backend-engineer"]
        self.assertEqual(skills, sorted(skills))
        self.assertIn("skills/", sig["skills"])


class TestMarkerSplicing(unittest.TestCase):
    BLOCK = f"{ds.BEGIN}\n- **Roles:** x (self)\n{ds.END}"

    def test_first_write_appends_section(self):
        text = "# Skill: demo\n\nBody prose.\n"
        out = ds._splice(text, self.BLOCK)
        self.assertTrue(out.startswith("# Skill: demo"))
        self.assertIn("## Signature", out)
        self.assertIn(self.BLOCK, out)

    def test_rewrite_replaces_only_the_block(self):
        text = "# Skill: demo\n\nBody prose.\n"
        once = ds._splice(text, self.BLOCK)
        newblock = f"{ds.BEGIN}\n- **Roles:** y (self)\n{ds.END}"
        twice = ds._splice(once, newblock)
        self.assertIn(newblock, twice)
        self.assertNotIn("x (self)", twice)         # old block gone
        self.assertEqual(twice.count(ds.BEGIN), 1)  # exactly one block
        self.assertEqual(twice.count("## Signature"), 1)  # heading preserved
        self.assertTrue(twice.startswith("# Skill: demo\n\nBody prose."))

    def test_prose_outside_markers_is_untouched(self):
        text = (f"# Skill: demo\n\nAlpha.\n\n## Signature\n\n{self.BLOCK}\n\n"
                "## Trailer\n\nOmega.\n")
        newblock = f"{ds.BEGIN}\n- **Roles:** z (self)\n{ds.END}"
        out = ds._splice(text, newblock)
        self.assertIn("Alpha.", out)
        self.assertIn("## Trailer", out)
        self.assertIn("Omega.", out)
        self.assertIn("z (self)", out)


class TestDriftDetection(unittest.TestCase):
    def _mini_corpus(self, root: Path) -> None:
        (root / ".Doctrine" / "roles").mkdir(parents=True)
        (root / ".Doctrine" / "skills").mkdir(parents=True)
        (root / ".Doctrine" / "roles" / "backend-engineer.md").write_text(
            "---\nname: backend-engineer\ndescription: d\n---\n\n"
            "**Mission.** Build.\n\n"
            "**Loads.** `skills/backend.md`, `skills/testing.md`\n",
            encoding="utf-8")
        (root / ".Doctrine" / "skills" / "backend.md").write_text(
            "# Skill: Backend\n\nBody.\n", encoding="utf-8")
        (root / ".Doctrine" / "skills" / "testing.md").write_text(
            "# Skill: Testing\n\nBody.\n", encoding="utf-8")

    def test_missing_then_written_then_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._mini_corpus(root)

            missing: list[str] = []
            ds.check(root, missing)
            self.assertEqual(len(missing), 3, missing)  # 1 role + 2 skills
            self.assertTrue(all("missing Signature" in f for f in missing))

            self.assertEqual(ds.write(root), 0)

            current: list[str] = []
            ds.check(root, current)
            self.assertEqual(current, [], "post-write corpus should be clean")

    def test_hand_edit_is_caught_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._mini_corpus(root)
            ds.write(root)
            skill = root / ".Doctrine" / "skills" / "backend.md"
            text = skill.read_text("utf-8")
            tampered = text.replace("(self)", "(TAMPERED)")
            self.assertNotEqual(tampered, text)
            skill.write_text(tampered, encoding="utf-8")

            stale: list[str] = []
            ds.check(root, stale)
            self.assertTrue(any("backend.md" in f and "stale" in f
                                for f in stale), stale)

    def test_used_by_inversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._mini_corpus(root)
            ds.write(root)
            testing = (root / ".Doctrine" / "skills" / "testing.md"
                       ).read_text("utf-8")
            block = ds._current_block(testing)
            self.assertIn("`roles/backend-engineer.md`", block)


class TestLintIntegration(unittest.TestCase):
    def test_lint_gates_signatures_in_source_only(self):
        import doctrine_lint as dl
        # Source repo: the live corpus is signed and current -> no findings.
        findings: list[str] = []
        dl.check_signatures(REPO, findings)
        self.assertEqual(findings, [])

    def test_consumer_repo_is_not_gated(self):
        import doctrine_lint as dl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A consumer pyproject (not "doctrineos") + an unsigned corpus:
            (root / "pyproject.toml").write_text(
                '[project]\nname = "openhawk"\n', encoding="utf-8")
            (root / ".Doctrine" / "roles").mkdir(parents=True)
            (root / ".Doctrine" / "roles" / "backend-engineer.md").write_text(
                "---\nname: x\ndescription: d\n---\n**Mission.** m\n",
                encoding="utf-8")
            findings: list[str] = []
            dl.check_signatures(root, findings)
            self.assertEqual(findings, [],
                             "consumer corpus must not be signature-gated")


if __name__ == "__main__":
    unittest.main()
