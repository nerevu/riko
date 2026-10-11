# vim: sw=4:ts=4:expandtab
"""Extracts the prose-bearing lines of shipped source and documentation files."""

from __future__ import annotations

from io import StringIO
from tokenize import COMMENT, FSTRING_MIDDLE, STRING, generate_tokens
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TEXT_SUFFIXES = frozenset({".rst", ".md"})


def _gen_python_text(source: str) -> Iterator[tuple[int, str]]:
    """Extracts each string literal, f-string text, and comment with its line."""
    for token in generate_tokens(StringIO(source).readline):
        if token.type in {STRING, FSTRING_MIDDLE, COMMENT}:
            for offset, line in enumerate(token.string.splitlines()):
                yield token.start[0] + offset, line


def gen_text(path: Path) -> Iterator[tuple[int, str]]:
    """
    Extracts the prose-bearing lines of a file with their line numbers.

    Args:

        path: A Python file (strings and comments only) or a prose file (every line).

    Yields:

        ``(lineno, line)`` pairs in file order.

    """
    source = path.read_text(encoding="utf-8")

    if path.suffix == ".py":
        yield from _gen_python_text(source)
    else:
        yield from enumerate(source.splitlines(), start=1)


def gen_files(root: Path, excluded: frozenset[str]) -> Iterator[Path]:
    """
    Expands a root into the Python and prose files to scan.

    Args:

        root: A directory to walk, or a single file.
        excluded: File names to skip wherever they appear.

    Yields:

        Each scannable file, in sorted path order.

    """
    candidates = sorted(root.rglob("*")) if root.is_dir() else [root]

    for path in candidates:
        scannable = path.suffix == ".py" or path.suffix in _TEXT_SUFFIXES

        if path.is_file() and scannable and path.name not in excluded:
            yield path


__all__ = ["gen_files", "gen_text"]
