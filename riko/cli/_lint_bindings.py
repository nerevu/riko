# vim: sw=4:ts=4:expandtab
"""
Checks code and doctests for a ``Workflow`` bound to ``workflow`` rather than ``flow``.

A parameter, local, module-level, or doctest binding that holds a ``Workflow`` is
named ``flow``. The name ``workflow`` is the decorator that tags a workflow module's
pipe. Instance fields (``pipeline.workflow``), the ``from_workflow`` constructor name,
and the ``workflow=`` keywords that set those fields keep their names, including a
method's keyword-only parameter named after its class's field
(``replace(*, workflow=None)``). Because those fields keep the name, a value read from
an attribute named ``workflow`` counts as a ``Workflow``.
"""

from __future__ import annotations

import ast
import re
from doctest import DocTestParser
from itertools import chain
from typing import TYPE_CHECKING, NamedTuple

from riko.base._iterutils import gen_instances

from ._import_graph import FUNCTION_NODES
from ._shipped_text import gen_files

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_WORKFLOW_TYPE = re.compile(r"\b(?:Workflow|WorkflowLike)\b")

_WORKFLOW_BUILDERS = frozenset(
    {
        "Workflow",
        "load_workflow",
        "Workflow.parse",
        "Workflow.from_raw",
        "require_workflow",
    }
)

_BINDINGS = (ast.arg, ast.Assign, ast.AnnAssign)
_DOCUMENTED = (ast.Module, ast.ClassDef, *FUNCTION_NODES)
RESERVED_NAME = "workflow"
PREFERRED_NAME = "flow"


class BindingIssue(NamedTuple):
    """
    One ``Workflow`` value bound to the reserved name.

    Attributes:

        path: The file containing the binding.
        lineno: The line the binding is on.

    """

    path: Path
    lineno: int

    def __str__(self) -> str:
        """Renders the issue as a ``path:line`` line naming the preferred binding."""
        where, found, instead = (
            f"{self.path}:{self.lineno}",
            RESERVED_NAME,
            PREFERRED_NAME,
        )
        return f"{where} {found!r} binds a Workflow -> use {instead!r}"


def _names_workflow(annotation: ast.expr | None) -> bool:
    """Detects an annotation that names ``Workflow`` or ``WorkflowLike``."""
    text = "" if annotation is None else ast.unparse(annotation)
    return bool(_WORKFLOW_TYPE.search(text))


def _get_workflow_helpers(tree: ast.Module) -> frozenset[str]:
    """Collects the functions whose return annotation names a ``Workflow``."""
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, FUNCTION_NODES) and _names_workflow(node.returns)
    )


def _holds_workflow(value: ast.expr | None, *helpers: str) -> bool:
    """
    Detects a value expression that produces a ``Workflow``.

    A call's target is named ``f`` for ``f()`` and ``g`` for ``x.g()``.
    """
    if isinstance(value, ast.Call):
        func = value.func

        if isinstance(func, ast.Name):
            callee = func.id
        elif isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id == "Workflow":
                callee = "Workflow"
            else:
                callee = func.attr
        else:
            callee = ""

        holds = callee in _WORKFLOW_BUILDERS.union(helpers)
    elif isinstance(value, ast.Attribute):
        holds = value.attr == RESERVED_NAME
    else:
        holds = False

    return holds


def _is_reserved(target: ast.expr) -> bool:
    """Detects an assignment target that is the bare reserved name."""
    return isinstance(target, ast.Name) and target.id == RESERVED_NAME


def _gen_field_keywords(cls: ast.ClassDef) -> Iterator[ast.arg]:
    """Generates the keyword-only method parameters named after one of the fields."""
    names = {
        statement.target.id
        for statement in cls.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    }

    for method in gen_instances(cls.body, FUNCTION_NODES):
        yield from (arg for arg in method.args.kwonlyargs if arg.arg in names)


def _gen_tree_lines(tree: ast.Module, *helpers: str) -> Iterator[int]:
    """
    Finds the line of each reserved-name ``Workflow`` binding in a tree.

    A binding is a parameter or assignment that binds a ``Workflow`` to the name.
    """
    classes = list(gen_instances(ast.walk(tree), ast.ClassDef))
    fields = set(map(id, chain.from_iterable(cls.body for cls in classes)))
    keywords = set(map(id, chain.from_iterable(map(_gen_field_keywords, classes))))
    bindings = (
        node
        for node in ast.walk(tree)
        if isinstance(node, _BINDINGS) and id(node) not in fields | keywords
    )

    for node in bindings:
        if isinstance(node, ast.arg):
            binds = node.arg == RESERVED_NAME and _names_workflow(node.annotation)
        elif isinstance(node, ast.Assign):
            reserved = any(map(_is_reserved, node.targets))
            binds = reserved and _holds_workflow(node.value, *helpers)
        elif _is_reserved(node.target):
            typed = _names_workflow(node.annotation)
            binds = typed or _holds_workflow(node.value, *helpers)
        else:
            binds = False

        if binds:
            yield node.lineno


def _gen_example_lines(text: str, start: int, *helpers: str) -> Iterator[int]:
    """Finds the line of each reserved-name ``Workflow`` binding in doctest text."""
    for example in DocTestParser().get_examples(text):
        try:
            tree = ast.parse(example.source)
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])

        for offset in _gen_tree_lines(tree, *helpers):
            yield start + example.lineno + offset - 1


def _gen_doctest_lines(tree: ast.Module, *helpers: str) -> Iterator[int]:
    """Finds the line of each reserved-name ``Workflow`` binding in a docstring."""
    docstrings = (
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, _DOCUMENTED)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    )

    for doc in docstrings:
        yield from _gen_example_lines(str(doc.value), doc.lineno, *helpers)


def gen_binding_lines(source: str, *, is_python: bool = True) -> Iterator[int]:
    """
    Finds each reserved-name ``Workflow`` binding in a source or prose file's text.

    Args:

        source: The text to check.

    Kwargs:

        is_python: Whether ``source`` is Python (code and docstring examples) rather
            than prose, whose doctest examples alone are checked.

    Yields:

        The line of each offending binding, in line order.

    Examples:

        >>> header = "def run(workflow: Workflow):\\n"
        >>> source = header + "    workflow = pipeline.workflow\\n"
        >>> list(gen_binding_lines(source))
        [1, 2]
        >>> list(gen_binding_lines(">>> workflow = Workflow()\\n", is_python=False))
        [1]

    """
    if is_python:
        tree = ast.parse(source)
        helpers = _get_workflow_helpers(tree)
        code_lines = _gen_tree_lines(tree, *helpers)
        lines = {*code_lines, *_gen_doctest_lines(tree, *helpers)}
    else:
        lines = set(_gen_example_lines(source, 1))

    yield from sorted(lines)


def gen_binding_issues(*roots: Path) -> Iterator[BindingIssue]:
    """
    Walks ``roots`` for a ``Workflow`` value bound to the reserved name.

    Python files are checked in code and docstring examples; ``.rst`` and ``.md``
    files in their doctest examples.

    Args:

        roots: Files or directories to scan.

    Yields:

        One :class:`BindingIssue` per binding, in path then line order.

    """
    for path in chain.from_iterable(map(gen_files, roots)):
        text = path.read_text(encoding="utf-8")
        is_python = path.suffix == ".py"

        for lineno in gen_binding_lines(text, is_python=is_python):
            yield BindingIssue(path, lineno)


__all__ = [
    "PREFERRED_NAME",
    "RESERVED_NAME",
    "BindingIssue",
    "gen_binding_issues",
    "gen_binding_lines",
]
