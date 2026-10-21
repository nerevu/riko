# vim: sw=4:ts=4:expandtab
"""Checks shipped text for banned phrases, phase codes, and removed ext paths."""

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
    BannedTerm("shutdown budget", "shutdown timeout"),
    BannedTerm("coroutine function", "async function"),
    BannedTerm("sink pipe", "write module, or 'consumes the stream'"),
    BannedTerm("output module", "the `PipeDef` `output` node"),
    BannedTerm("cross-mode", "sync or async"),
    BannedTerm("host-mode", "sync or async"),
    BannedTerm("other mode", "sync or async"),
    BannedTerm("both sides", "sync and async"),
    BannedTerm("other side", "the sync or async counterpart"),
    BannedTerm("chosen side", "the sync or async interface"),
    BannedTerm("each side", "sync and async"),
    BannedTerm("missing side", "the missing sync or async interface"),
    BannedTerm("terminal sub-source", "secondary input stream"),
    BannedTerm("input requirements", "input declarations"),
    BannedTerm("keyword sink", "`**kwargs` or keyword arguments"),
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
    BannedTerm("provider package", "extension package"),
    BannedTerm("provider command", "backend command"),
)

_EXCLUDED_NAMES = frozenset(
    {"CHANGES.rst", "MIGRATION.rst", "_lint_terms.py", "test_cli.py"}
)


def _build_pattern(term: BannedTerm) -> re.Pattern[str]:
    """Compiles a phrase into a whole-word, case-insensitive pattern."""
    return re.compile(rf"\b{re.escape(term.phrase)}s?\b", re.IGNORECASE)


PHASE_CODE = BannedTerm("phase code", "a plain-English name for the pending work")
REMOVED_EXT_PATH = BannedTerm(
    "removed riko.ext submodule path", "`riko.ext` or one of its submodules"
)

_PHRASE_PATTERNS: tuple[tuple[BannedTerm, re.Pattern[str]], ...] = tuple(
    (term, _build_pattern(term)) for term in BANNED_TERMS
)
_PATTERNS: tuple[tuple[BannedTerm, re.Pattern[str]], ...] = (
    *_PHRASE_PATTERNS,
    (PHASE_CODE, re.compile(r"\b[RP](?:1[0-2]|[0-9])[A-E]?(?:\.\d+)?\b")),
    (
        REMOVED_EXT_PATH,
        re.compile(r"\briko\.ext\.(?:config|decorators|names|protocols|registry)\b"),
    ),
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

    def __str__(self) -> str:
        """Renders the issue as a ``path:line 'found' -> say 'instead'`` line."""
        found, instead = self.found, self.term.instead
        return f"{self.path}:{self.lineno} {found!r} -> say {instead!r}"


def _gen_issues(
    patterns: tuple[tuple[BannedTerm, re.Pattern[str]], ...], *roots: Path
) -> Iterator[TermIssue]:
    """Walks ``roots`` for every ``patterns`` match in their scannable files."""
    for root in roots:
        for path in gen_files(root, _EXCLUDED_NAMES):
            for lineno, line in gen_text(path):
                for term, pattern in patterns:
                    for match in pattern.finditer(line):
                        yield TermIssue(path, lineno, match.group(0), term)


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
    yield from _gen_issues(_PATTERNS, *roots)


def gen_phrase_issues(*roots: Path) -> Iterator[TermIssue]:
    """
    Walks ``roots`` for banned phrases only, leaving phase codes and old paths alone.

    The internal docs cite phases and retired paths by design, so they are held to the
    reserved terms but not to the rules for shipped text.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`TermIssue` per match, in path then line order.

    """
    yield from _gen_issues(_PHRASE_PATTERNS, *roots)


__all__ = [
    "BANNED_TERMS",
    "PHASE_CODE",
    "REMOVED_EXT_PATH",
    "BannedTerm",
    "TermIssue",
    "gen_phrase_issues",
    "gen_term_issues",
]
