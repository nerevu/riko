"""Tests for the reserved-terms lint check."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from riko.base._paths import ROOT_DIR
from riko.cli._lint_terms import BANNED_TERMS, BannedTerm, iter_term_issues

if TYPE_CHECKING:
    from pathlib import Path

STANDARD = ROOT_DIR / "_docs" / "DOCUMENTATION_STANDARD.md"


def _reserved_terms_section() -> str:
    text = STANDARD.read_text(encoding="utf-8")
    return text.split("## Reserved terms", 1)[1].split("\n## ", 1)[0].lower()


@pytest.mark.parametrize("term", BANNED_TERMS, ids=lambda term: term.phrase)
def test_every_banned_phrase_has_a_reserved_terms_ruling(term: BannedTerm) -> None:
    assert term.phrase.lower() in _reserved_terms_section()


def test_python_strings_and_comments_are_checked_but_code_is_not(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "cross_mode = 1  # a cross-mode bridge\n"
        'MESSAGE = "two Execution Contexts"\n'
        "def other_mode(): ...\n"
        'ERROR = f"{ref} in the other mode"\n',
        encoding="utf-8",
    )
    found = [(issue.lineno, issue.found) for issue in iter_term_issues(source)]
    assert found == [(1, "cross-mode"), (2, "Execution Contexts"), (4, "other mode")]


def test_prose_files_are_checked_except_the_changelog(tmp_path: Path) -> None:
    (tmp_path / "GUIDE.rst").write_text("Run a sub-pipeline.\n", encoding="utf-8")
    (tmp_path / "CHANGES.rst").write_text("Run a sub-pipeline.\n", encoding="utf-8")
    found = [issue.path.name for issue in iter_term_issues(tmp_path)]
    assert found == ["GUIDE.rst"]
