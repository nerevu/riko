# vim: sw=4:ts=4:expandtab
"""
Docstring-style checks (PRIVATE).

Scans Python source for function docstring summaries that begin with ``Returns`` or
``Yields``, which the documentation standard forbids: the summary names the action,
while the output belongs in the ``Returns:``/``Yields:`` section. Backs the
``manage lint --docstrings`` check.

Examples:

    Basic usage::

        >>> from riko.cli._docstyle import summary_leads_with_output
        >>>
        >>> summary_leads_with_output("Returns the parsed response body.")
        True
        >>> summary_leads_with_output("Parses the response body.")
        False

"""

from ast import AsyncFunctionDef, FunctionDef, get_docstring, parse, walk
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

BANNED_LEADS: tuple[str, ...] = ("Return", "Yield")


class SummaryIssue(NamedTuple):
    """
    A function whose docstring summary leads with the output, not the action.

    Attributes:

        path: The file containing the offending function.
        lineno: The line the function is defined on.
        name: The function's name.
        summary: The offending first line of its docstring.

    """

    path: Path
    lineno: int
    name: str
    summary: str


def summary_leads_with_output(summary: str) -> bool:
    """
    Detects a docstring summary that opens with ``Returns``/``Yields``.

    Args:

        summary: The first line of a docstring.

    Returns:

        Whether the first word is a banned output verb.

    """
    first = summary.strip().split(" ", 1)[0].rstrip(".:,")
    return any(first.startswith(lead) for lead in BANNED_LEADS)


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Expands a root into the Python files under it (or itself, for a file)."""
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    yield from files


def iter_summary_issues(*roots: Path) -> Iterator[SummaryIssue]:
    """
    Walks ``roots`` for function docstrings whose summary leads with the output.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`SummaryIssue` per offending function, in path then line order.

    """
    for root in roots:
        for path in _iter_python_files(root):
            tree = parse(path.read_text(encoding="utf-8"))

            for node in walk(tree):
                if not isinstance(node, (FunctionDef, AsyncFunctionDef)):
                    continue

                doc = get_docstring(node)
                summary = doc.strip().split("\n", 1)[0].strip() if doc else ""

                if summary and summary_leads_with_output(summary):
                    yield SummaryIssue(path, node.lineno, node.name, summary)


def format_issue(issue: SummaryIssue) -> str:
    """Renders one issue as a ``path:line name() -> 'summary'`` line."""
    return f"{issue.path}:{issue.lineno} {issue.name}() -> {issue.summary!r}"


__all__ = [
    "BANNED_LEADS",
    "SummaryIssue",
    "format_issue",
    "iter_summary_issues",
    "summary_leads_with_output",
]
