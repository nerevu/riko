# vim: sw=4:ts=4:expandtab
"""Checks docstring summaries and examples against the Riko documentation rules."""

from __future__ import annotations

from ast import (
    AnnAssign,
    Assign,
    AsyncFunctionDef,
    ClassDef,
    FunctionDef,
    ImportFrom,
    Module,
    Name,
    TypeAlias,
    get_docstring,
    parse,
    walk,
)
from doctest import DocTestParser
from typing import TYPE_CHECKING, NamedTuple

from riko.base._api_surface import EXT_CODEGEN, EXTENSION, STABLE, TYPES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

BANNED_LEADS: tuple[str, ...] = ("Return", "Yield")
_PUBLIC_NAMES: frozenset[str] = STABLE | EXTENSION | EXT_CODEGEN | TYPES
_PUBLIC_PATHS: tuple[tuple[str, frozenset[str]], ...] = (
    ("riko", STABLE),
    ("riko.ext", EXTENSION),
    ("riko.ext.codegen", EXT_CODEGEN),
    ("riko.types", TYPES),
)


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


def resolve_public_path(name: str) -> str | None:
    """
    Finds the supported import path of a public name.

    Args:

        name: An importable name.

    Returns:

        The first of ``riko``, ``riko.ext``, ``riko.ext.codegen``, or ``riko.types``
        that exports ``name``, or ``None`` when no supported path does.

    Examples:

        >>> resolve_public_path("Pipeline")
        'riko'
        >>> resolve_public_path("processor")
        'riko.ext'
        >>> resolve_public_path("summary_leads_with_output") is None
        True

    """
    return next((path for path, names in _PUBLIC_PATHS if name in names), None)


def _is_private_path(module: str) -> bool:
    """Detects a ``riko`` module path with an underscore-prefixed segment."""
    segments = module.split(".")
    return segments[0] == "riko" and any(seg.startswith("_") for seg in segments[1:])


def gen_private_imports(doc: str) -> Iterator[tuple[str, str, str]]:
    """
    Finds doctest imports of public names through private module paths.

    Args:

        doc: A cleaned docstring.

    Yields:

        The offending import line, the imported name, and its public path.

    Examples:

        >>> doc = ">>> from riko.runtime._pipeline import Pipeline"
        >>> list(gen_private_imports(doc))
        [('from riko.runtime._pipeline import Pipeline', 'Pipeline', 'riko')]
        >>> list(gen_private_imports(">>> from riko import Pipeline"))
        []

    """
    for example in DocTestParser().get_examples(doc):
        try:
            tree = parse(example.source)
        except SyntaxError:
            tree = Module(body=[], type_ignores=[])

        lines = example.source.splitlines()
        imports = (
            node
            for node in walk(tree)
            if isinstance(node, ImportFrom)
            and node.module is not None
            and _is_private_path(node.module)
        )

        for node in imports:
            for alias in node.names:
                public = resolve_public_path(alias.name)

                if public is not None:
                    yield lines[node.lineno - 1].strip(), alias.name, public


def _gen_defined_names(tree: Module) -> Iterator[str]:
    """Lists the names a module's top-level statements define."""
    for node in tree.body:
        if isinstance(node, (FunctionDef, AsyncFunctionDef, ClassDef)):
            yield node.name
        elif isinstance(node, Assign):
            for target in node.targets:
                yield from (name.id for name in walk(target) if isinstance(name, Name))
        elif isinstance(node, (AnnAssign, TypeAlias)):
            target = node.target if isinstance(node, AnnAssign) else node.name

            if isinstance(target, Name):
                yield target.id


def _gen_module_example_issues(path: Path, tree: Module) -> Iterator[DocstringIssue]:
    """Flags a module example in a private module that defines no public name."""
    doc = get_docstring(tree) or ""
    private = path.name.startswith("_") and path.name != "__init__.py"
    exported = not _PUBLIC_NAMES.isdisjoint(_gen_defined_names(tree))

    if private and not exported and DocTestParser().get_examples(doc):
        problem = "private module without a public API carries a module example"
        first = next(line.strip() for line in doc.splitlines() if ">>>" in line)
        yield DocstringIssue(path, 1, "<module>", problem, first)


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Expands a root into the Python files under it (or itself, for a file)."""
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    yield from files


def gen_docstring_issues(*roots: Path) -> Iterator[DocstringIssue]:
    """
    Walks ``roots`` for docstrings that break the summary or example rules.

    Function summaries must not lead with the output; no docstring may narrate
    between its doctest examples or import a public name through a private module;
    and a private module without a public API carries no module example.

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

                for line, imported, public in gen_private_imports(doc):
                    problem = (
                        f"imports {imported} privately "
                        f'(use "from {public} import {imported}")'
                    )
                    yield DocstringIssue(path, lineno, name, problem, line)

            yield from _gen_module_example_issues(path, tree)


def format_issue(issue: DocstringIssue) -> str:
    """Renders one issue as a ``path:line name() problem: 'text'`` line."""
    return f"{issue.path}:{issue.lineno} {issue.name}() {issue.problem}: {issue.text!r}"


__all__ = [
    "BANNED_LEADS",
    "DocstringIssue",
    "format_issue",
    "gen_docstring_issues",
    "gen_example_prose",
    "gen_private_imports",
    "resolve_public_path",
    "summary_leads_with_output",
]
