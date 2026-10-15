# vim: sw=4:ts=4:expandtab
"""Checks docstring summaries and examples against the Riko documentation rules."""

from __future__ import annotations

from ast import (
    AsyncFunctionDef,
    ClassDef,
    FunctionDef,
    Module,
    get_docstring,
    parse,
    walk,
)
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

BANNED_LEADS: tuple[str, ...] = ("Return", "Yield")


class DocstringIssue(NamedTuple):
    """
    A docstring that breaks a documentation rule.

    Attributes:

        path: The file containing the docstring.
        lineno: The line its module, class, or function is defined on.
        name: The function or class name, or ``"<module>"``.
        problem: The rule it breaks.
        text: The offending docstring line.

    """

    path: Path
    lineno: int
    name: str
    problem: str
    text: str


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


def gen_example_prose(doc: str) -> Iterator[str]:
    """
    Finds prose paragraphs that narrate between doctest examples.

    A paragraph that follows an example and introduces the next one belongs in a
    ``>>> #`` comment instead. A paragraph ending in ``::`` labels a new example
    group and is allowed.

    Args:

        doc: A cleaned docstring.

    Yields:

        The first line of each narrating paragraph.

    Examples:

        >>> doc = ">>> f(1)\\n1\\n\\nWith two:\\n\\n>>> f(2)\\n2"
        >>> list(gen_example_prose(doc))
        ['With two:']
        >>> list(gen_example_prose(">>> f(1)\\n1\\n\\n>>> # With two\\n>>> f(2)\\n2"))
        []

    """
    lines = [line.strip() for line in doc.splitlines()]
    started = False

    for i, line in enumerate(lines):
        starts_paragraph = started and line and (i == 0 or not lines[i - 1])
        started = started or line.startswith(">>>")

        if starts_paragraph and not line.startswith((">>>", "...")):
            end = next((j for j in range(i, len(lines)) if not lines[j]), len(lines))
            following = next((rest for rest in lines[end:] if rest), "")

            if following.startswith(">>>") and not lines[end - 1].endswith("::"):
                yield line


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Expands a root into the Python files under it (or itself, for a file)."""
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    yield from files


def gen_docstring_issues(*roots: Path) -> Iterator[DocstringIssue]:
    """
    Walks ``roots`` for docstrings that break the summary or example rules.

    Function summaries must not lead with the output, and no docstring may narrate
    between its doctest examples.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`DocstringIssue` per offending line, in path then line order.

    """
    for root in roots:
        for path in _iter_python_files(root):
            tree = parse(path.read_text(encoding="utf-8"))
            nodes = (
                node
                for node in walk(tree)
                if isinstance(node, (Module, ClassDef, FunctionDef, AsyncFunctionDef))
            )

            for node in sorted(nodes, key=lambda node: getattr(node, "lineno", 0)):
                doc = get_docstring(node) or ""
                summary = doc.strip().split("\n", 1)[0].strip()
                lineno = getattr(node, "lineno", 1)
                name = getattr(node, "name", "<module>")
                is_function = isinstance(node, (FunctionDef, AsyncFunctionDef))

                if is_function and summary and summary_leads_with_output(summary):
                    problem = "summary leads with the output"
                    yield DocstringIssue(path, lineno, name, problem, summary)

                for prose in gen_example_prose(doc):
                    problem = "narrates between examples (use a >>> # comment)"
                    yield DocstringIssue(path, lineno, name, problem, prose)


def format_issue(issue: DocstringIssue) -> str:
    """Renders one issue as a ``path:line name() problem: 'text'`` line."""
    return f"{issue.path}:{issue.lineno} {issue.name}() {issue.problem}: {issue.text!r}"


__all__ = [
    "BANNED_LEADS",
    "DocstringIssue",
    "format_issue",
    "gen_docstring_issues",
    "gen_example_prose",
    "summary_leads_with_output",
]
