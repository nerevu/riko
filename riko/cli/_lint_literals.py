# vim: sw=4:ts=4:expandtab
"""Checks shipped text for inline literals that break the string-value quoting rules."""

from __future__ import annotations

import ast
import re
from itertools import chain
from operator import attrgetter
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
_BARE_STRING_DEFAULT = LiteralRule(
    re.compile(r"^\s*\**(\w+)(?: \([^)]*\))?: .*\(default: ([^\s\"`()]+)\)"),
    'a quoted string default, e.g. (default: "content")',
)


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

    def __str__(self) -> str:
        """Renders the issue as a ``path:line 'found' -> use instead`` line."""
        found, instead = self.found, self.rule.instead
        return f"{self.path}:{self.lineno} {found!r} -> use {instead}"


def _get_string_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str]:
    """Maps each parameter whose signature default is a string to that string."""
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaulted = positional[len(positional) - len(args.defaults) :]
    pairs = [
        *zip(defaulted, args.defaults, strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]
    return {
        arg.arg: default.value
        for arg, default in pairs
        if isinstance(default, ast.Constant) and isinstance(default.value, str)
    }


def _gen_bare_default_issues(path: Path) -> Iterator[LiteralIssue]:
    """Flags a docstring ``(default: word)`` whose parameter defaults to ``"word"``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
    )

    for node in nodes:
        doc = node.body[0]
        value = doc.value if isinstance(doc, ast.Expr) else None

        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            defaults = _get_string_defaults(node)

            for offset, line in enumerate(value.value.splitlines()):
                match = _BARE_STRING_DEFAULT.pattern.match(line)

                if match and defaults.get(match.group(1)) == match.group(2):
                    found = f"(default: {match.group(2)})"
                    yield LiteralIssue(
                        path, doc.lineno + offset, found, _BARE_STRING_DEFAULT
                    )


def gen_literal_issues(*roots: Path) -> Iterator[LiteralIssue]:
    """
    Walks ``roots`` for inline literals in Python strings/comments and prose files.

    Flags a double-backtick literal in a ``(default: …)`` slot (an ``ALL_CAPS``
    constant name is allowed), a single-quoted string value such as ``'x'``
    written as a literal, and a docstring ``(default: word)`` left unquoted when the
    parameter's signature default is that string.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`LiteralIssue` per match, in path then line order.

    """
    for root in roots:
        for path in gen_files(root, _EXCLUDED_NAMES):
            text_issues = (
                LiteralIssue(path, lineno, match.group(0), rule)
                for lineno, line in gen_text(path)
                for rule in LITERAL_RULES
                for match in rule.pattern.finditer(line)
            )
            is_python = path.suffix == ".py"
            default_issues = _gen_bare_default_issues(path) if is_python else ()
            issues = chain(text_issues, default_issues)
            yield from sorted(issues, key=attrgetter("lineno"))


__all__ = ["LITERAL_RULES", "LiteralIssue", "LiteralRule", "gen_literal_issues"]
