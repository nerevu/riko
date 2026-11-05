# vim: sw=4:ts=4:expandtab
"""
Generates each test tier's ``__init__.py`` from the subjects its files declare.

The whole file is generated: a do-not-edit header, then a docstring holding the
tier's one-line summary and its index, with one row per test file naming the
subjects it owns, in file order. A subject is a top-level ``Test<Subject>`` class
name without its ``Test`` prefix; an ``Async<Subject>`` twin shares the row entry of
its ``<Subject>`` or ``Sync<Subject>`` class.
"""

from __future__ import annotations

import ast
import textwrap
from typing import TYPE_CHECKING

from riko.base._paths import TESTS_DIR
from riko.base._strutils import get_codegen_note

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_LINE_LENGTH = 88
_INDENT = " " * 4
_GAP = " " * 4

TIER_SUMMARIES = {
    "public": "Provides public API tests: tests that use only supported names.",
    "internal": "Provides internal tests: mechanics, drift guards, and failure modes.",
    "functional": (
        "Provides functional tests: CLI commands, examples, and stored workflows "
        "end to end."
    ),
}

TIERS = tuple(TIER_SUMMARIES)
GENERATED_HEADER = f"# {get_codegen_note('--tests')}"
INDEX_HEADER = "Index (file, then the subjects it owns, in file order):"


def gen_subjects(tree: ast.Module) -> Iterator[tuple[str, ast.ClassDef]]:
    """
    Walks a test module for the index subjects its top-level classes own.

    Args:

        tree: The parsed test module.

    Yields:

        Each top-level ``Test<Subject>`` class's ``<Subject>`` and class, in file
        order, except a ``TestAsync<Subject>`` twin whose ``<Subject>`` or
        ``Sync<Subject>`` class is in the same module.

    Examples:

        >>> tree = ast.parse("class TestSend: ...\\nclass TestAsyncSend: ...")
        >>> [subject for subject, _ in gen_subjects(tree)]
        ['Send']

    """
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test")
    ]
    names = {node.name for node in classes}

    for node in classes:
        base = node.name.removeprefix("TestAsync")
        twinned = base != node.name and bool({f"Test{base}", f"TestSync{base}"} & names)

        if not twinned:
            yield node.name.removeprefix("Test"), node


def _build_row(name: str, *subjects: str, width: int) -> str:
    """Renders one file's row, wrapping its subjects under the subject column."""
    lead = f"{_INDENT}{name.ljust(width)}{_GAP}"
    text = ", ".join(subjects)
    wrapped = textwrap.fill(
        text,
        width=_LINE_LENGTH,
        initial_indent=lead,
        subsequent_indent=" " * len(lead),
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped if text else lead.rstrip()


def _gen_rows(tier: Path) -> Iterator[str]:
    paths = sorted(tier.glob("test_*.py"))
    width = max((len(path.name) for path in paths), default=0)

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        subjects = [subject for subject, _ in gen_subjects(tree)]
        row = _build_row(path.name, *subjects, width=width)
        yield f"{row}\n"


def build_index_rows(tier: Path) -> str:
    """
    Renders a tier folder's index rows from its test files.

    Args:

        tier: The tier folder, such as ``tests/public``.

    Returns:

        One row per ``test_*.py`` file in name order, each line ending in a newline.

    """
    return "".join(_gen_rows(tier))


def generate_tier_index(tier: Path) -> str:
    """
    Generates a tier folder's ``__init__.py`` source with a current index.

    Args:

        tier: The tier folder, such as ``tests/public``.

    Returns:

        The whole ``__init__.py`` source: the generated-file header, then a
        docstring with the tier's summary and its index rows.

    Raises:

        ValueError: If the folder is not one of the test tiers.

    """
    summary = TIER_SUMMARIES.get(tier.name)

    if summary is None:
        raise ValueError(f"{tier.name!r} is not a test tier: {', '.join(TIERS)}")

    rows = build_index_rows(tier)
    return f'{GENERATED_HEADER}\n\n"""\n{summary}\n\n{INDEX_HEADER}\n\n{rows}"""\n'


def main() -> int:
    """Regenerates every test tier's index."""
    for name in TIERS:
        init = TESTS_DIR / name / "__init__.py"
        init.write_text(generate_tier_index(init.parent), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
