# vim: sw=4:ts=4:expandtab
"""Checks docstring summaries and examples against the Riko documentation rules."""

from __future__ import annotations

import re
from ast import (
    AnnAssign,
    Assign,
    AsyncFunctionDef,
    Attribute,
    ClassDef,
    ImportFrom,
    Module,
    Name,
    Subscript,
    TypeAlias,
    expr,
    get_docstring,
    parse,
    walk,
)
from doctest import DocTestParser
from typing import TYPE_CHECKING, NamedTuple

from riko.base._api_surface import EXT_CODEGEN, EXTENSION, STABLE, TYPES
from riko.base._verbs import VERBS

from ._import_graph import FUNCTION_NODES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_RAISES_ENTRY: re.Pattern[str] = re.compile(r"[\w.]+:(\s|$)")
_NONE_CHECK: re.Pattern[str] = re.compile(r">>> .* is None")
_LEAD_VERBS: dict[str, str] = {rule.lead: rule.verb for rule in VERBS}
_NAME_VERBS: frozenset[str] = frozenset(_LEAD_VERBS.values())
_TYPE_ONLY_BASES: frozenset[str] = frozenset({"Protocol", "TypedDict"})
_EXCEPTION_SUFFIXES: tuple[str, ...] = ("Error", "Exception", "Warning")
_PUBLIC_NAMES: frozenset[str] = STABLE | EXTENSION | EXT_CODEGEN | TYPES

_PUBLIC_PATHS: tuple[tuple[str, frozenset[str]], ...] = (
    ("riko", STABLE),
    ("riko.ext", EXTENSION),
    ("riko.ext.codegen", EXT_CODEGEN),
    ("riko.types", TYPES),
)

BANNED_LEADS: tuple[str, ...] = ("Return", "Yield")

COMPOUND_FUNCTIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("_require_guards.py", "require_from_attrs"),
        ("_require_guards.py", "require_from_form"),
        ("_require_guards.py", "require_from_keys"),
        ("_require_guards.py", "require_from_typed_dict"),
    }
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

    def __str__(self) -> str:
        """Renders the issue as a ``path:line name() problem: 'text'`` line."""
        return f"{self.path}:{self.lineno} {self.name}() {self.problem}: {self.text!r}"


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


def get_name_verb(name: str, *, is_async: bool = False) -> str | None:
    """
    Gets the general-purpose verb a function name starts with.

    Skips leading underscores, ``async_`` prefix, and the ``a`` prefix of a coroutine
    named for its synchronous twin.

    Args:

        name: The function name.
        is_async: Whether the function is an async function.

    Returns:

        The verb, or ``None`` when the name starts with none of them.

    Examples:

        >>> get_name_verb("_build_item_call")
        'build'
        >>> get_name_verb("_aload_settings", is_async=True)
        'load'
        >>> get_name_verb("async_get_temp_file")
        'get'
        >>> get_name_verb("gen_items")

    """
    first = name.lstrip("_").removeprefix("async_").split("_", 1)[0]
    twin = first.removeprefix("a") if is_async else first
    verb = twin if twin in _NAME_VERBS else first
    return verb if verb in _NAME_VERBS else None


def get_summary_verb(summary: str) -> str | None:
    """
    Gets the general-purpose verb a docstring summary starts with.

    Args:

        summary: The first line of a docstring.

    Returns:

        The verb, or ``None`` when the summary starts with none of them.

    Examples:

        >>> get_summary_verb("Resolves a seed to one stream.")
        'resolve'
        >>> get_summary_verb("Finds the first match.")

    """
    return _LEAD_VERBS.get(summary.strip().split(" ", 1)[0])


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


def gen_malformed_raises(doc: str) -> Iterator[str]:
    """
    Finds ``Raises:`` entries that do not start with an exception name and a colon.

    Args:

        doc: A cleaned docstring.

    Yields:

        Each entry line that does not read ``SomeError: description``.

    Examples:

        >>> doc = "Raises:\\n\\n    ValueError: If bad.\\n    KeyError if missing.\\n"
        >>> list(gen_malformed_raises(doc))
        ['KeyError if missing.']

    """
    section: int | None = None
    entry: int | None = None

    for raw in doc.splitlines():
        indent, line = len(raw) - len(raw.lstrip()), raw.strip()

        if line == "Raises:":
            section, entry = indent, None
        elif section is None or not line:
            continue
        elif indent <= section:
            section = None
        elif entry is None or indent <= entry:
            entry = indent

            if not _RAISES_ENTRY.match(line):
                yield line


def gen_none_checks(doc: str) -> Iterator[str]:
    """
    Finds doctest lines that check for ``None`` instead of showing the result.

    A call that returns ``None`` shows no output, so the bare call already
    demonstrates it.

    Args:

        doc: A cleaned docstring.

    Yields:

        Each ``>>>`` line ending in ``is None``.

    Examples:

        >>> doc = ">>> f(1) is None\\nTrue\\n>>> f(2)\\n"
        >>> list(gen_none_checks(doc))
        ['>>> f(1) is None']

    """
    lines = (line.strip() for line in doc.splitlines())
    yield from (line for line in lines if _NONE_CHECK.fullmatch(line))


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
        >>> resolve_public_path("summary_leads_with_output")

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


def _get_base_name(base: expr) -> str:
    """Gets the bare class name of a base expression such as ``typing.Protocol[T]``."""
    node = base.value if isinstance(base, Subscript) else base
    name = ""

    if isinstance(node, Attribute):
        name = node.attr
    elif isinstance(node, Name):
        name = node.id

    return name


def _gen_defined_names(tree: Module) -> Iterator[str]:
    """Lists the names a module's top-level statements define."""
    for node in tree.body:
        if isinstance(node, (*FUNCTION_NODES, ClassDef)):
            yield node.name
        elif isinstance(node, Assign):
            for target in node.targets:
                yield from (name.id for name in walk(target) if isinstance(name, Name))
        elif isinstance(node, (AnnAssign, TypeAlias)):
            target = node.target if isinstance(node, AnnAssign) else node.name

            if isinstance(target, Name):
                yield target.id


def _gen_runtime_names(tree: Module) -> Iterator[str]:
    """
    Lists the functions and classes a module defines that do something when used.

    Type-only classes (protocols and typed dicts, directly or through a base defined in
    the same module) and exceptions do not count.

    """
    type_only: set[str] = set(_TYPE_ONLY_BASES)

    for node in tree.body:
        if isinstance(node, FUNCTION_NODES):
            yield node.name
        elif isinstance(node, ClassDef):
            bases = set(map(_get_base_name, node.bases))

            if not type_only.isdisjoint(bases):
                type_only.add(node.name)
            elif not node.name.endswith(_EXCEPTION_SUFFIXES):
                yield node.name


def _gen_module_example_issues(path: Path, tree: Module) -> Iterator[DocstringIssue]:
    """
    Flags a private module whose module example does not match its public API.

    A private module that defines no public name carries no module example, and one
    whose public names include a runtime function or class must carry one.

    """
    doc = get_docstring(tree) or ""
    private = path.name.startswith("_") and path.name != "__init__.py"
    exported = not _PUBLIC_NAMES.isdisjoint(_gen_defined_names(tree))
    runtime = sorted(_PUBLIC_NAMES.intersection(_gen_runtime_names(tree)))
    has_example = bool(DocTestParser().get_examples(doc))

    if private and not exported and has_example:
        problem = "private module without a public API carries a module example"
        first = next(line.strip() for line in doc.splitlines() if ">>>" in line)
        yield DocstringIssue(path, 1, "<module>", problem, first)
    elif private and runtime and not has_example:
        problem = "private module with a public runtime API has no module example"
        yield DocstringIssue(path, 1, "<module>", problem, ", ".join(runtime))


def _iter_python_files(root: Path) -> Iterator[Path]:
    """Expands a root into the Python files under it (or itself, for a file)."""
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    yield from files


def gen_docstring_issues(*roots: Path) -> Iterator[DocstringIssue]:
    """
    Walks ``roots`` for docstrings that break the summary or example rules.

    Function summaries must not lead with the output or with a different general-purpose
    verb than the function name. No docstring may narrate between its doctest examples,
    check a result with ``is None``, or import a public name through a private module.
    A private module without a public API carries no module example, and one with a
    public runtime API carries one.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`DocstringIssue` per offending line, in path then line order.

    """
    types = (Module, ClassDef, *FUNCTION_NODES)

    for root in roots:
        for path in _iter_python_files(root):
            tree = parse(path.read_text(encoding="utf-8"))
            nodes = (node for node in walk(tree) if isinstance(node, types))

            for node in sorted(nodes, key=lambda node: getattr(node, "lineno", 0)):
                doc = get_docstring(node) or ""
                summary = doc.strip().split("\n", 1)[0].strip()
                lineno = getattr(node, "lineno", 1)
                name = getattr(node, "name", "<module>")
                is_function = isinstance(node, FUNCTION_NODES)

                if is_function and summary and summary_leads_with_output(summary):
                    problem = "summary leads with the output"
                    yield DocstringIssue(path, lineno, name, problem, summary)

                if is_function and (path.name, name) not in COMPOUND_FUNCTIONS:
                    is_async = isinstance(node, AsyncFunctionDef)
                    name_verb = get_name_verb(name, is_async=is_async)
                    summary_verb = get_summary_verb(summary)

                    if name_verb is not None and summary_verb not in {None, name_verb}:
                        problem = "summary verb does not match the name verb "
                        problem += name_verb
                        yield DocstringIssue(path, lineno, name, problem, summary)

                for entry in gen_malformed_raises(doc):
                    problem = "Raises: entry does not start with 'SomeError:'"
                    yield DocstringIssue(path, lineno, name, problem, entry)

                for prose in gen_example_prose(doc):
                    problem = "narrates between examples (use a >>> # comment)"
                    yield DocstringIssue(path, lineno, name, problem, prose)

                for check in gen_none_checks(doc):
                    problem = "checks for None (show the bare call instead)"
                    yield DocstringIssue(path, lineno, name, problem, check)

                for line, imported, public in gen_private_imports(doc):
                    problem = (
                        f"imports {imported} privately "
                        f'(use "from {public} import {imported}")'
                    )
                    yield DocstringIssue(path, lineno, name, problem, line)

            yield from _gen_module_example_issues(path, tree)


__all__ = [
    "BANNED_LEADS",
    "COMPOUND_FUNCTIONS",
    "DocstringIssue",
    "gen_docstring_issues",
    "gen_example_prose",
    "gen_malformed_raises",
    "gen_none_checks",
    "gen_private_imports",
    "get_name_verb",
    "get_summary_verb",
    "resolve_public_path",
    "summary_leads_with_output",
]
