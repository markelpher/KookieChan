"""Valida o changelog da versão antes da publicação de uma release."""

import re
import sys
from pathlib import Path


def changelog_for_tag(text: str, tag: str) -> str:
    version = tag.removeprefix("v")
    headings = re.findall(r"(?m)^## \[([^\]\r\n]+)\](?:\s+-\s+[^\r\n]+)?\s*$", text)
    if not version or headings != [version]:
        raise ValueError(
            "O changelog deve conter somente a versão correspondente à tag."
        )
    if not re.search(r"(?m)^###\s+\S", text) or not re.search(r"(?m)^-\s+\S", text):
        raise ValueError("O changelog deve conter uma categoria e uma alteração.")
    return text.strip() + "\n"


def main() -> None:
    try:
        text = Path("CHANGELOG.md").read_text(encoding="utf-8")
        print(changelog_for_tag(text, sys.argv[1]), end="")
    except (IndexError, OSError, UnicodeError, ValueError) as exc:
        print(f"Changelog inválido: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
