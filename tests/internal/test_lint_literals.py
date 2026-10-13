"""Tests for the inline-literal quoting lint check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.cli._lint_literals import gen_literal_issues

if TYPE_CHECKING:
    from pathlib import Path


def test_python_strings_and_comments_are_checked_but_code_is_not(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "fmt = 'list'  # fmt may be ``'list'``\n"
        '"""field (str): Item field (default: ``"content"``)."""\n'
        "def f(x=\"``'x'``\"): ...\n",
        encoding="utf-8",
    )
    found = [(issue.lineno, issue.found) for issue in gen_literal_issues(source)]
    assert found == [(1, "``'list'``"), (2, '(default: ``"content"``'), (3, "``'x'``")]


def test_plain_defaults_constant_names_and_double_quotes_pass(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        '"""\n'
        'field (str): Item field (default: "content").\n'
        "limit: Maximum calls (default: ``DEF_CONCURRENCY_LIMIT``).\n"
        'executor: One of ``"thread"`` or ``"process"``; yields ``""``.\n'
        '"""\n',
        encoding="utf-8",
    )
    assert list(gen_literal_issues(source)) == []


def test_prose_files_are_checked_including_the_changelog(tmp_path: Path) -> None:
    (tmp_path / "GUIDE.rst").write_text("Set ``'auto'``.\n", encoding="utf-8")
    (tmp_path / "CHANGES.rst").write_text("Set ``'auto'``.\n", encoding="utf-8")
    found = [issue.path.name for issue in gen_literal_issues(tmp_path)]
    assert found == ["CHANGES.rst", "GUIDE.rst"]
