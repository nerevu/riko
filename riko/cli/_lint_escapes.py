# vim: sw=4:ts=4:expandtab

"""
Counts the package's type-checker escapes: ``typing.Any`` and ``typing.cast`` uses.

Both opt out of checking, so each count has a ceiling recorded in ``pyproject.toml``
under ``[tool.riko.typing]`` that only ever ratchets down. Quoted type expressions
(string annotations, a ``cast`` target, a quoted subscript) count like bare ones.
"""

from __future__ import annotations

import ast
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_TYPING_MODULES = frozenset({"typing", "typing_extensions"})
ESCAPES: tuple[str, ...] = ("Any", "cast")


class _EscapeCounter(ast.NodeVisitor):
    """Counts one module's escapes, given the local names typing's escapes bind."""

    def __init__(self, aliases: dict[str, str], modules: frozenset[str]) -> None:
        self.aliases = aliases
        self.modules = modules
        self.counts: Counter[str] = Counter()

    def _get_escape(self, node: ast.expr) -> str | None:
        """Gets the escape ``node`` names, if it names one."""
        if isinstance(node, ast.Name):
            escape = self.aliases.get(node.id)
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in self.modules
            and node.attr in ESCAPES
        ):
            escape = node.attr
        else:
            escape = None

        return escape

    def _visit_type(self, node: ast.expr | None) -> None:
        """Counts ``Any`` in a type expression, parsing any quoted part."""
        for child in () if node is None else ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                try:
                    parsed = ast.parse(child.value, mode="eval")
                except SyntaxError:
                    continue

                self._visit_type(parsed.body)
            elif isinstance(child, ast.Name | ast.Attribute):
                self.counts["Any"] += self._get_escape(child) == "Any"

    def _visit_quoted(self, node: ast.expr | None) -> None:
        """Counts ``Any`` in ``node`` when it is a quoted type expression."""
        if isinstance(node, ast.Constant):
            self._visit_type(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Counts a bare ``Any``."""
        self.counts["Any"] += self._get_escape(node) == "Any"

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Counts a qualified ``typing.Any``."""
        self.counts["Any"] += self._get_escape(node) == "Any"
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Counts a ``cast`` call and any ``Any`` in a quoted cast target."""
        if self._get_escape(node.func) == "cast":
            self.counts["cast"] += 1

            if node.args:
                self._visit_quoted(node.args[0])

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Counts ``Any`` in a quoted subscript such as ``Base["T[Any]"]``."""
        parts = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]

        for part in parts:
            self._visit_quoted(part)

        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        """Counts ``Any`` in a quoted parameter annotation."""
        self._visit_quoted(node.annotation)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Counts ``Any`` in a quoted variable annotation."""
        self._visit_quoted(node.annotation)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Counts ``Any`` in a quoted return annotation."""
        self._visit_quoted(node.returns)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Counts ``Any`` in a quoted coroutine return annotation."""
        self._visit_quoted(node.returns)
        self.generic_visit(node)


def _get_typing_names(tree: ast.Module) -> tuple[dict[str, str], frozenset[str]]:
    """Gets the local names bound to typing's escapes, and to typing itself."""
    aliases: dict[str, str] = {}
    modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _TYPING_MODULES:
            for alias in node.names:
                if alias.name in ESCAPES:
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _TYPING_MODULES:
                    modules.add(alias.asname or alias.name)

    return aliases, frozenset(modules)


def get_escape_counts(source: str) -> Counter[str]:
    """
    Gets one module's ``Any`` references and ``cast`` calls.

    Args:

        source: The module's source code.

    Returns:

        The count of each escape, keyed by ``"Any"`` and ``"cast"``.

    Examples:

        >>> source = "from typing import Any, cast\\nx: 'list[Any]' = cast(Any, y)"
        >>> sorted(get_escape_counts(source).items())
        [('Any', 2), ('cast', 1)]

    """
    tree = ast.parse(source)
    counter = _EscapeCounter(*_get_typing_names(tree))
    counter.visit(tree)
    return Counter({escape: counter.counts[escape] for escape in ESCAPES})


def gen_escape_counts(*roots: Path) -> Iterator[tuple[Path, Counter[str]]]:
    """
    Finds the escapes in each module under ``roots``.

    Args:

        roots: The package folders to scan.

    Yields:

        Each module with at least one escape, and its counts.

    """
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            counts = get_escape_counts(path.read_text(encoding="utf-8"))

            if counts.total():
                yield path, counts
