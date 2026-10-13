# vim: sw=4:ts=4:expandtab

"""
Checks that the test suite follows its indexed layout.

Each test tier folder (``public``, ``internal``, ``functional``) indexes its files in
its ``__init__.py`` docstring: one row per file naming the subjects it owns. The
check holds every test file to its row, every test to a ``Test<Subject>`` class, and
keeps private names out of the public tier. File sizes outside the split/merge bounds
are reported as advice rather than failures.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

TIERS = ("public", "internal", "functional")
FIXTURE_DIRS = frozenset({"workflows", "pyworkflows", "dags", "typing"})
SPLIT_LINES = 2000
MERGE_LINES = 300
HISTORY_NAMES = re.compile(r"^test_(regressions?|fixes|bugs?|misc)\b")

_INDEX_HEADER = "Index (file"
_ROW = re.compile(r"^ {4}(test_\w+\.py)\s+(.*)$")
_CONTINUATION = re.compile(r"^ {8,}(\S.*)$")


class LayoutIssue(NamedTuple):
    """A test-layout finding; ``fatal`` findings fail the check."""

    path: Path
    lineno: int
    message: str
    fatal: bool = True


def _split_subjects(text: str) -> list[str]:
    return [subject.strip() for subject in text.split(",") if subject.strip()]


def parse_index(docstring: str) -> dict[str, tuple[str, ...]]:
    """
    Parses a tier index into its file rows and their subjects.

    Args:

        docstring: The tier folder's ``__init__.py`` docstring.

    Returns:

        Each indexed file name with the subjects its row lists, in order.

    Raises:

        ValueError: If the docstring has no index.

    Examples:

        >>> index = parse_index('''
        ... Index (file, then the subjects it owns, in file order):
        ...
        ...     test_pipeline.py    PipelineConstruction, Close,
        ...                         ExportFormats
        ... ''')
        >>> index["test_pipeline.py"]
        ('PipelineConstruction', 'Close', 'ExportFormats')

    """
    if _INDEX_HEADER not in docstring:
        raise ValueError("the docstring has no test index")

    rows: dict[str, list[str]] = {}
    current = None

    for line in docstring.split(_INDEX_HEADER, 1)[1].splitlines():
        row = _ROW.match(line)
        continued = _CONTINUATION.match(line)

        if row is not None:
            current = row.group(1)
            rows[current] = _split_subjects(row.group(2))
        elif continued is not None and current is not None:
            rows[current].extend(_split_subjects(continued.group(1)))

    return {name: tuple(subjects) for name, subjects in rows.items()}


def _is_listed(class_name: str, subjects: tuple[str, ...]) -> bool:
    stem = class_name.removeprefix("Test")
    base = stem.removeprefix("Async")
    return bool({stem, base, f"Sync{base}"} & set(subjects))


def _gen_file_issues(
    path: Path, subjects: tuple[str, ...], public: bool
) -> Iterator[LayoutIssue]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    lines = len(text.splitlines())

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                message = f"{node.name} must live in a Test<Subject> class"
                yield LayoutIssue(path, node.lineno, message)
        elif (
            isinstance(node, ast.ClassDef)
            and node.name.startswith("Test")
            and not _is_listed(node.name, subjects)
        ):
            message = f"{node.name} names no subject in the index row"
            yield LayoutIssue(path, node.lineno, message)

    if public:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.startswith("_"):
                        message = f"public tests import supported names: {alias.name}"
                        yield LayoutIssue(path, node.lineno, message)

    if lines > SPLIT_LINES:
        message = f"{lines} lines; split its largest index row into its own file"
        yield LayoutIssue(path, 1, message, fatal=False)
    elif lines < MERGE_LINES:
        message = f"{lines} lines; consider merging it into a neighboring file"
        yield LayoutIssue(path, 1, message, fatal=False)


def _gen_tier_issues(tier: Path) -> Iterator[LayoutIssue]:
    init = tier / "__init__.py"
    docstring = (
        ast.get_docstring(ast.parse(init.read_text(encoding="utf-8")), clean=False)
        or ""
    )

    try:
        index = parse_index(docstring)
    except ValueError as error:
        yield LayoutIssue(init, 1, str(error))
        index = {}

    seen: dict[str, str] = {}

    for name, subjects in index.items():
        for subject in subjects:
            if subject in seen:
                message = f"{subject} is indexed under both {seen[subject]} and {name}"
                yield LayoutIssue(init, 1, message)

            seen.setdefault(subject, name)

        if not (tier / name).exists():
            yield LayoutIssue(init, 1, f"{name} is indexed but does not exist")

    modules = (path for path in sorted(tier.glob("*.py")) if path.name != "__init__.py")

    for path in modules:
        if not path.name.startswith("test_"):
            message = "shared helpers belong in a tests/_*.py module"
            yield LayoutIssue(path, 1, message)
        elif HISTORY_NAMES.match(path.name):
            message = "name the file for its subject, not its history"
            yield LayoutIssue(path, 1, message)
        elif path.name not in index:
            yield LayoutIssue(path, 1, f"{path.name} has no row in {init.name}")
        else:
            public = tier.name == "public"
            yield from _gen_file_issues(path, index[path.name], public)


def gen_layout_issues(tests_dir: Path) -> Iterator[LayoutIssue]:
    """
    Finds every way ``tests_dir`` departs from the indexed test layout.

    Args:

        tests_dir: The suite's root folder (``tests``).

    Yields:

        One finding per layout departure, failing or advisory.

    """
    allowed = {*TIERS, *FIXTURE_DIRS, "__pycache__"}

    for path in sorted(tests_dir.iterdir()):
        if path.is_dir() and path.name not in allowed:
            message = f"unexpected folder; tests live in {', '.join(TIERS)}"
            yield LayoutIssue(path, 1, message)
        elif path.is_file() and path.name.startswith("test_"):
            yield LayoutIssue(path, 1, f"test files live in {', '.join(TIERS)}")

    for tier in TIERS:
        if (tests_dir / tier).is_dir():
            yield from _gen_tier_issues(tests_dir / tier)


def format_layout_issue(issue: LayoutIssue) -> str:
    """
    Formats a layout finding as a ``path:line: message`` diagnostic.

    Args:

        issue: The finding to format.

    Returns:

        The diagnostic line, marked as advice when the finding does not fail.

    """
    kind = "error" if issue.fatal else "advice"
    return f"{issue.path}:{issue.lineno}: {kind}: {issue.message}"
