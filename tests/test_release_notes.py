"""Testes da geração das notas de versão."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1] / ".github" / "scripts" / "release_notes.py"
)
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
assert spec and spec.loader
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


class ReleaseNotesTests(unittest.TestCase):
    def test_matching_tags_preserve_markdown(self):
        text = "# Changelog\n\n## [1.2.3] - 2026-11-03\n\n### Correções\n\n- Ajuste.\n"
        for tag in ("1.2.3", "v1.2.3"):
            with self.subTest(tag=tag):
                self.assertEqual(release_notes.changelog_for_tag(text, tag), text)

    def test_mismatched_or_multiple_versions_fail(self):
        for text in (
            "## [1.2.2]\n### Alterações\n- Ajuste.\n",
            "## [1.2.3]\n### Alterações\n- Ajuste.\n## [1.2.2]\n### Anterior\n- Outro.\n",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                release_notes.changelog_for_tag(text, "v1.2.3")

    def test_missing_category_or_item_fails(self):
        for text in ("## [1.2.3]\n- Ajuste.\n", "## [1.2.3]\n### Alterações\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                release_notes.changelog_for_tag(text, "1.2.3")


if __name__ == "__main__":
    unittest.main()
