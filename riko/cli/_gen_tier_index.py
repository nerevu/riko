# vim: sw=4:ts=4:expandtab
"""
Generates each test tier's index from the subjects its files declare.

A tier folder's ``__init__.py`` docstring ends with an index: one row per test file
naming the subjects it owns, in file order. A subject is a top-level ``Test<Subject>``
class name without its ``Test`` prefix; an ``Async<Subject>`` twin shares the row entry
of its ``<Subject>`` or ``Sync<Subject>`` class.
"""

from __future__ import annotations

import ast
import re
import textwrap
from typing import TYPE_CHECKING

from riko.base._paths import TESTS_DIR

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TIERS = ("public", "internal", "functional")
INDEX_HEADER = "Index (file, then the subjects it owns, in file order):"
_LINE_LENGTH = 88
_INDENT = " " * 4
_GAP = " " * 4
_INDEX = re.compile(
    rf"(?P<head>^{re.escape(INDEX_HEADER)}\n\n).*?(?P<tail>^\"\"\"$)",
    re.MULTILINE | re.DOTALL,
)


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
    Regenerates a tier folder's ``__init__.py`` source with a current index.

    Args:

        tier: The tier folder, such as ``tests/public``.

    Returns:

        The ``__init__.py`` source with every row after the index header replaced.

    Raises:

        ValueError: If the docstring does not end with an index header.

    """
    text = (tier / "__init__.py").read_text(encoding="utf-8")
    rows = build_index_rows(tier)
    repl = lambda match: f"{match['head']}{rows}{match['tail']}"
    generated, count = _INDEX.subn(repl, text, count=1)

    if not count:
        raise ValueError(f"the docstring has no {INDEX_HEADER!r} block")

    return generated


def main() -> int:
    """Regenerates every test tier's index."""
    for name in TIERS:
        init = TESTS_DIR / name / "__init__.py"
        init.write_text(generate_tier_index(init.parent), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
