"""Testes das convenções estruturais do código Python."""

import ast
import unittest
from pathlib import Path


class CodeConventionTest(unittest.TestCase):
    def test_python_modules_have_module_docstrings(self):
        repository_root = Path(__file__).resolve().parents[1]
        excluded = {".git", ".venv", "venv", "__pycache__"}
        for path in repository_root.rglob("*.py"):
            if any(
                part in excluded for part in path.relative_to(repository_root).parts
            ):
                continue
            with self.subTest(path=path.relative_to(repository_root)):
                module = ast.parse(path.read_text(encoding="utf-8"))
                self.assertIsNotNone(ast.get_docstring(module, clean=False))

    def test_source_classes_and_functions_use_comments_instead_of_docstrings(self):
        source_root = Path(__file__).resolve().parents[1] / "src"
        for path in source_root.rglob("*.py"):
            with self.subTest(path=path.relative_to(source_root)):
                module = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(module):
                    if isinstance(
                        node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                    ):
                        self.assertIsNone(ast.get_docstring(node))
