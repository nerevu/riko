# vim: sw=4:ts=4:expandtab
"""Checks shipped text for inline literals that break the string-value quoting rules."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from ._shipped_text import gen_files, gen_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class LiteralRule(NamedTuple):
    """
    One inline-literal form shipped text must not use, with the form that replaces it.

    Attributes:

        pattern: Matches the offending form.
        instead: The form the quoting rules call for.

    """

    pattern: re.Pattern[str]
    instead: str


LITERAL_RULES: tuple[LiteralRule, ...] = (
    LiteralRule(
        re.compile(r"\(default: ``(?![A-Z][A-Z0-9_]*``)[^`]*``"),
        'a plain-text default, e.g. (default: "content")',
    ),
    LiteralRule(re.compile(r"``'[^`]*'``"), 'a double-quoted value, e.g. ``"x"``'),
)

_EXCLUDED_NAMES = frozenset({"_lint_literals.py", "test_cli.py"})


class LiteralIssue(NamedTuple):
    """
    One offending inline literal found in shipped text.

    Attributes:

        path: The file containing the literal.
        lineno: The line the literal is on.
        found: The text the rule matched.
        rule: The rule it broke.

    """

    path: Path
    lineno: int
    found: str
    rule: LiteralRule


def gen_literal_issues(*roots: Path) -> Iterator[LiteralIssue]:
    """
    Walks ``roots`` for inline literals in Python strings/comments and prose files.

    Flags a double-backtick literal in a ``(default: …)`` slot (an ``ALL_CAPS``
    constant name is allowed) and a single-quoted string value such as ``'x'``
    written as a literal.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`LiteralIssue` per match, in path then line order.

    """
    for root in roots:
        for path in gen_files(root, _EXCLUDED_NAMES):
            for lineno, line in gen_text(path):
                for rule in LITERAL_RULES:
                    for match in rule.pattern.finditer(line):
                        yield LiteralIssue(path, lineno, match.group(0), rule)


def format_literal_issue(issue: LiteralIssue) -> str:
    """Renders one issue as a ``path:line 'found' -> use instead`` line."""
    found, instead = issue.found, issue.rule.instead
    return f"{issue.path}:{issue.lineno} {found!r} -> use {instead}"


__all__ = [
    "LITERAL_RULES",
    "LiteralIssue",
    "LiteralRule",
    "format_literal_issue",
    "gen_literal_issues",
]
