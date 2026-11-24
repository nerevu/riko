# vim: sw=4:ts=4:expandtab
"""
Checks the execution layer for streams that no owner closes.

Ownership follows the data: a stream an execution builds is closed by the adapter that
reads it, by a close-once wrapper, or by the run's own registrars. Here an owner is
the wrapper or adapter that closes a stream once it ends. Three rules hold:

- no ``_Owned`` wrapper: a foreign closable becomes a close-once value only through
  ``auto_close``/``aauto_close``;
- ``add`` on a run (``run.add``, or ``self.add`` inside ``_RunStream``) only inside the
  run's registrars (``_register_port``, ``build_envelope_stream``,
  ``abuild_envelope_stream``, ``_call_and_take``), the splitter builders that register
  the values several ports read (``_build_splitter_ports``, ``_abuild_splitter_ports``),
  or ``_RunStream`` itself;
- a stream factory's result (``amap``, ``aislice``, ``async_iter``, ``as_async``,
  ``to_async``, ``to_sync``, the unwrap and envelope adapters) reaches an owner in the
  function that builds it: it is an owner's argument, returned or yielded, used as a
  ``with`` context, set on a run attribute, or bound to a name that one of those later
  receives.
  ``yield from`` hands the stream to the delegating generator, which closes it. Besides
  the factories and close-once wrappers, the executions' own adapters own what they
  are given: ``_to_async``/``_to_sync`` re-expose a sync stream as async or the
  reverse, ``_resolve_node_inputs`` hands its roots to the node's readers, and
  ``map_inputs`` hands each stream to the reader it builds. The node builders
  (``_build_envelope_stream``, ``_build_splitter_ports``, ``_run_async_node``, and their
  async twins) own the input stream they are given. A name packed into a tuple or list
  that is later splatted into one of those counts as handed on. ``list`` and ``tuple``
  are not owners: one that fails or is interrupted mid-read leaves the stream open, so
  drain inside ``closing``.

Known limits: only direct arguments, and containers, conditionals, and comprehensions
around them, are followed, so a stream stored in another record or passed to a
constructor that holds it is reported; ``as_async`` counts as a factory whatever its
argument, though it returns an async stream unchanged; ``for``/``async for`` directly
over a factory call is reported for sync and async alike, since an early ``break``
drops the stream unclosed; a name counts as owned when any owner receives it on or
after the line that binds it, whichever branch that owner is on.
"""

from __future__ import annotations

import ast
from itertools import chain
from typing import TYPE_CHECKING, NamedTuple

from ._import_graph import FUNCTION_NODES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_OWNED = "_Owned"
_RUN_STREAM = "_RunStream"
_RUN_NAMES = frozenset({"run", "_run"})
_REGISTRARS = frozenset(
    {
        "_register_port",
        "build_envelope_stream",
        "abuild_envelope_stream",
        "_call_and_take",
        "_build_splitter_ports",
        "_abuild_splitter_ports",
        _RUN_STREAM,
    }
)

_FACTORIES = frozenset(
    {
        "amap",
        "aislice",
        "async_iter",
        "as_async",
        "_aunwrap",
        "_unwrap",
        "to_async",
        "to_sync",
        "gen_values",
        "agen_values",
        "gen_envelopes",
        "agen_envelopes",
        "gen_result_envelopes",
        "agen_result_envelopes",
    }
)

_OWNERS = _FACTORIES | {
    "auto_close",
    "aauto_close",
    "maybe_closing",
    "maybe_aclosing",
    "aclosing",
    "closing",
    "_register_port",
    "register_owned",
    "_to_async",
    "_to_sync",
    "_resolve_node_inputs",
    "map_inputs",
}

_BUILDERS = frozenset(
    {
        "_build_envelope_stream",
        "_abuild_envelope_stream",
        "_build_splitter_ports",
        "_abuild_splitter_ports",
        "_run_async_node",
        "_run_sync_node",
    }
)

_WRAPPERS = (
    ast.Tuple,
    ast.List,
    ast.Set,
    ast.Starred,
    ast.IfExp,
    ast.Await,
    ast.ListComp,
    ast.SetComp,
    ast.GeneratorExp,
)

_HANDOFFS = (ast.Return, ast.Yield, ast.YieldFrom, ast.Lambda, ast.withitem)
_BINDINGS = (ast.AnnAssign, ast.NamedExpr)
OWNED_MESSAGE = "`_Owned` -> adopt the value with auto_close or aauto_close"
ADD_MESSAGE = "run.add outside the run's registrars -> let an owning adapter close it"
DROPPED_MESSAGE = "result reaches no owner -> pass it to one or return it"


class OwnershipIssue(NamedTuple):
    """
    One stream the execution layer builds or registers outside the ownership rules.

    Attributes:

        path: The file containing the call.
        lineno: The line the call is on.
        message: What the rule found and what to do instead.

    """

    path: Path
    lineno: int
    message: str

    def __str__(self) -> str:
        """Renders the issue as a ``path:line`` line followed by its message."""
        return f"{self.path}:{self.lineno} {self.message}"


def _get_callee(call: ast.Call) -> str | None:
    """Gets the name or attribute a call invokes, if it invokes one."""
    func = call.func

    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        name = None

    return name


def _is_run(node: ast.expr, in_run_stream: bool) -> bool:
    """Checks whether ``node`` names a run, ``self`` included inside ``_RunStream``."""
    if isinstance(node, ast.Name):
        is_self = in_run_stream and node.id == "self"
        result = node.id in _RUN_NAMES or is_self
    else:
        result = isinstance(node, ast.Attribute) and node.attr in _RUN_NAMES

    return result


def _is_owner(call: ast.Call) -> bool:
    """Checks whether ``call`` takes ownership of the streams passed to it."""
    func = call.func
    run_add = (
        isinstance(func, ast.Attribute)
        and func.attr == "add"
        and _is_run(func.value, False)
    )
    return run_add or _get_callee(call) in _OWNERS


def _gen_own_nodes(function: ast.AST) -> Iterator[ast.AST]:
    """Walks the nodes of ``function``'s body, skipping nested function bodies."""
    stack = list(ast.iter_child_nodes(function))

    while stack:
        node = stack.pop()
        yield node

        if not isinstance(node, FUNCTION_NODES):
            stack.extend(ast.iter_child_nodes(node))


def _get_arguments(call: ast.Call) -> list[ast.expr]:
    """Gets a call's positional (starred included) and keyword argument expressions."""
    return [*call.args, *(keyword.value for keyword in call.keywords)]


def _is_handoff(node: ast.AST, parent: ast.AST | None) -> bool:
    """Checks whether ``parent`` hands ``node`` to an owner without binding it."""
    if isinstance(parent, ast.Call):
        owns = _is_owner(parent) or _get_callee(parent) in _BUILDERS
        result = owns and node in _get_arguments(parent)
    elif isinstance(parent, ast.Assign):
        targets = parent.targets
        result = any(
            isinstance(t, ast.Attribute) and _is_run(t.value, False) for t in targets
        )
    else:
        result = isinstance(parent, _HANDOFFS)

    return result


class _FunctionScan:
    """Finds the factory calls one function builds whose results reach no owner."""

    def __init__(self, function: ast.AST) -> None:
        self.nodes = list(_gen_own_nodes(function))
        self.parents = {
            child: node for node in self.nodes for child in ast.iter_child_nodes(node)
        }

    def _climb(self, node: ast.AST) -> tuple[ast.AST, ast.AST | None]:
        """Climbs from ``node`` through containers to the expression holding it."""
        parent = self.parents.get(node)

        while isinstance(parent, _WRAPPERS):
            node, parent = parent, self.parents.get(parent)

        return node, parent

    def _gen_bound_names(self, node: ast.AST, parent: ast.AST) -> Iterator[str]:
        """Finds the names an assignment of ``node`` binds."""
        targets: list[ast.expr]

        if isinstance(parent, ast.Assign) and parent.value is node:
            targets = parent.targets
        elif isinstance(parent, _BINDINGS) and parent.value is node:
            targets = [parent.target]
        else:
            targets = []

        for target in targets:
            for child in ast.walk(target):
                if isinstance(child, ast.Name):
                    yield child.id

    def gen_handed_names(self) -> Iterator[tuple[str, int]]:
        """
        Finds each name handed to an owner, with the line it is handed on.

        A name packed into another name's value counts as handed when that name is
        handed on the same line or later.
        """
        handed: set[tuple[str, int]] = set()
        flows: list[tuple[str, int, set[str]]] = []

        for node in self.nodes:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                expr, parent = self._climb(node)

                if _is_handoff(expr, parent):
                    handed.add((node.id, node.lineno))
                elif parent is not None:
                    bound = set(self._gen_bound_names(expr, parent))
                    flows.append((node.id, node.lineno, bound))

        added = True

        while added:
            new = {
                (name, line)
                for name, line, bound in flows
                if any(b in bound and ln >= line for b, ln in handed)
            }
            added = not new <= handed
            handed |= new

        yield from handed

    def gen_dropped(self) -> Iterator[ast.Call]:
        """Finds the factory calls whose results reach no owner."""
        handed = list(self.gen_handed_names())

        for node in self.nodes:
            if isinstance(node, ast.Call) and _get_callee(node) in _FACTORIES:
                expr, parent = self._climb(node)
                bound = self._gen_bound_names(expr, parent) if parent else ()
                names = set(bound)
                later = any(n in names and ln >= node.lineno for n, ln in handed)

                if not (_is_handoff(expr, parent) or later):
                    yield node


class _OwnershipVisitor(ast.NodeVisitor):
    """Collects one module's ownership issues as ``(line, message)`` pairs."""

    def __init__(self) -> None:
        self.scopes: list[str] = []
        self.owned_names = {_OWNED}
        self.lines: list[tuple[int, str]] = []

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Flags an import of ``_Owned`` and remembers its local name."""
        for alias in node.names:
            if alias.name == _OWNED:
                self.owned_names.add(alias.asname or alias.name)
                self.lines.append((node.lineno, OWNED_MESSAGE))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Flags an ``_Owned`` class and scans the class body in its scope."""
        if node.name == _OWNED:
            self.lines.append((node.lineno, OWNED_MESSAGE))

        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Flags the factory results ``node`` drops and scans it in its scope."""
        scan = _FunctionScan(node).gen_dropped()
        found = ((c.lineno, f"`{_get_callee(c)}` {DROPPED_MESSAGE}") for c in scan)
        self.lines.extend(found)
        self.scopes.append(node.name)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Flags the factory results a function drops."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Flags the factory results an async function drops."""
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Flags an ``_Owned`` call or argument, and a misplaced ``run.add``."""
        func = node.func
        names = [func, *node.args]
        uses_owned = any(
            isinstance(n, ast.Name) and n.id in self.owned_names for n in names
        )
        in_run_stream = _RUN_STREAM in self.scopes
        run_add = (
            isinstance(func, ast.Attribute)
            and func.attr == "add"
            and _is_run(func.value, in_run_stream)
        )
        registrar = _REGISTRARS.intersection(self.scopes)

        if uses_owned:
            self.lines.append((node.lineno, OWNED_MESSAGE))

        if run_add and not registrar:
            self.lines.append((node.lineno, ADD_MESSAGE))

        self.generic_visit(node)


def gen_ownership_lines(source: str) -> Iterator[tuple[int, str]]:
    """
    Finds one module's streams built or registered outside the ownership rules.

    Args:

        source: The module's source code.

    Yields:

        Each issue's line and message, in line order.

    Examples:

        >>> source = "def f(s):\\n    amap(str, s)\\n    return amap(str, s)\\n"
        >>> [line for line, _ in gen_ownership_lines(source)]
        [2]
        >>> source = "def f(run, s):\\n    run.add(s)\\n"
        >>> list(gen_ownership_lines(source))[0][1].startswith("run.add")
        True

    """
    visitor = _OwnershipVisitor()
    visitor.visit(ast.parse(source))
    yield from sorted(set(visitor.lines))


def gen_ownership_issues(*roots: Path) -> Iterator[OwnershipIssue]:
    """
    Walks ``roots`` for streams built or registered outside the ownership rules.

    Args:

        roots: Python files or directories to scan.

    Yields:

        One :class:`OwnershipIssue` per finding, in path then line order.

    """
    paths = (sorted(r.rglob("*.py")) if r.is_dir() else [r] for r in roots)

    for path in chain.from_iterable(paths):
        for lineno, message in gen_ownership_lines(path.read_text(encoding="utf-8")):
            yield OwnershipIssue(path, lineno, message)


__all__ = [
    "ADD_MESSAGE",
    "DROPPED_MESSAGE",
    "OWNED_MESSAGE",
    "OwnershipIssue",
    "gen_ownership_issues",
    "gen_ownership_lines",
]
