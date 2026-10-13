# vim: sw=4:ts=4:expandtab
"""Checks shipped text for phrases the reserved-terms rules replace."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from ._shipped_text import gen_files, gen_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class BannedTerm(NamedTuple):
    """
    A phrase shipped text must not use, with the wording that replaces it.

    Attributes:

        phrase: The banned phrase (case-insensitive, whole words, optional plural).
        instead: The replacement wording the reserved-terms rules give.

    """

    phrase: str
    instead: str


BANNED_TERMS: tuple[BannedTerm, ...] = (
    BannedTerm("execution context", "run environment (a `Context`)"),
    BannedTerm("coroutine function", "async function"),
    BannedTerm("sink pipe", "write module, or 'consumes the stream'"),
    BannedTerm("output module", "the `PipeDef` `output` node"),
    BannedTerm("cross-mode", "sync or async"),
    BannedTerm("host-mode", "sync or async"),
    BannedTerm("other mode", "sync or async"),
    BannedTerm("terminal sub-source", "secondary input stream"),
    BannedTerm("input requirements", "input declarations"),
    BannedTerm("named workflow", "stored workflow"),
    BannedTerm("registered workflow", "stored workflow"),
    BannedTerm("imported workflow", "resolved workflow"),
    BannedTerm("sub-pipeline", "stored workflow"),
    BannedTerm("canonical workflow", "`Workflow`"),
    BannedTerm("authoring mapping", "`RawWorkflow`"),
    BannedTerm("canonical document", "workflow document"),
    BannedTerm("v2 document", "workflow document"),
    BannedTerm("pipeline JSON", "workflow document"),
    BannedTerm("DAG document", "serialized `PipeDag`"),
    BannedTerm("compiled pipeline", "workflow module"),
    BannedTerm("pipe file", "pipe script"),
    BannedTerm("wrapper options", "decoration options"),
    BannedTerm("decorator options", "decoration options"),
    BannedTerm("call-time options", "call options or keyword arguments"),
    BannedTerm("export target", "export format"),
    BannedTerm("destination type", "cast type"),
    BannedTerm("item attribute", "item field"),
    BannedTerm("resolver façade", "dispatcher"),
    BannedTerm("entry-point plugin", "extension package"),
)

_EXCLUDED_NAMES = frozenset(
    {"CHANGES.rst", "MIGRATION.rst", "_lint_terms.py", "test_cli.py"}
)


def _build_pattern(term: BannedTerm) -> re.Pattern[str]:
    """Compiles a phrase into a whole-word, case-insensitive pattern."""
    return re.compile(rf"\b{re.escape(term.phrase)}s?\b", re.IGNORECASE)


_PATTERNS: tuple[tuple[BannedTerm, re.Pattern[str]], ...] = tuple(
    (term, _build_pattern(term)) for term in BANNED_TERMS
)


class TermIssue(NamedTuple):
    """
    One banned phrase found in shipped text.

    Attributes:

        path: The file containing the phrase.
        lineno: The line the phrase is on.
        found: The phrase as written.
        term: The banned term it matched.

    """

    path: Path
    lineno: int
    found: str
    term: BannedTerm


def gen_term_issues(*roots: Path) -> Iterator[TermIssue]:
    """
    Walks ``roots`` for banned phrases in Python strings/comments and prose files.

    Args:

        roots: Files or directories to scan; the changelog and migration guide
            are skipped because they quote released wording, and the banned list
            and its tests because they spell out every phrase.

    Yields:

        One :class:`TermIssue` per match, in path then line order.

    """
    for root in roots:
        for path in gen_files(root, _EXCLUDED_NAMES):
            for lineno, line in gen_text(path):
                for term, pattern in _PATTERNS:
                    for match in pattern.finditer(line):
                        yield TermIssue(path, lineno, match.group(0), term)


def format_term_issue(issue: TermIssue) -> str:
    """Renders one issue as a ``path:line 'found' -> say 'instead'`` line."""
    found, instead = issue.found, issue.term.instead
    return f"{issue.path}:{issue.lineno} {found!r} -> say {instead!r}"


__all__ = [
    "BANNED_TERMS",
    "BannedTerm",
    "TermIssue",
    "format_term_issue",
    "gen_term_issues",
]
