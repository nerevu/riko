# vim: sw=4:ts=4:expandtab
"""
riko.modules._inference
~~~~~~~~~~~~~~~~~~~~~~~~
Return-kind inference for operator pipes: return-annotation analysis, generator
detection, and a narrow AST heuristic for short unannotated pipes.
"""

import ast
import builtins
import textwrap
from ast import AsyncFunctionDef, FunctionDef
from collections.abc import Awaitable, Coroutine, Iterator
from inspect import getsource, isasyncgenfunction, isgeneratorfunction, unwrap
from types import UnionType
from typing import (
    Annotated,
    Any,
    NamedTuple,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)
from typing import cast as cast_type

import pygogo as gogo

from riko.types.general import Pipeline
from riko.types.modules import Inference, OperatorReturnKind
from riko.types.values import NonstreamExpressions

logger = gogo.Gogo(__name__, monolog=True).logger

_STREAM_CALLS = {"aiter", "enumerate", "filter", "iter", "map", "reversed", "zip"}

_NONSTREAM_CALLS = {
    "abs",
    "all",
    "any",
    "bool",
    "bytearray",
    "bytes",
    "complex",
    "dict",
    "float",
    "frozenset",
    "int",
    "len",
    "list",
    "max",
    "min",
    "range",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
}

_PASSTHROUGH_NAMESPACES = ("asyncio.", "bado.", "riko.bado.")


class AnnotationMember(NamedTuple):
    annotation: object
    candidate: object


def _unwrap_alias(annotation: object) -> object:
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__

    return annotation


def _gen_members(annotation: object) -> Iterator[AnnotationMember]:
    annotation = _unwrap_alias(annotation)
    args = get_args(annotation)
    origin = get_origin(annotation)

    if origin in {Union, UnionType}:
        for arg in args:
            yield from _gen_members(arg)
    elif origin is Annotated:
        yield from _gen_members(args[0])
    elif origin in {Awaitable, Coroutine}:
        if args:
            yield from _gen_members(args[-1])
    else:
        yield AnnotationMember(annotation, origin or annotation)


def _matches_abc(candidate: object, abc: type) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, abc)


def _expression_path(node: ast.expr) -> str | None:
    path = None

    if isinstance(node, ast.Name):
        path = node.id
    elif isinstance(node, ast.Attribute) and (parent := _expression_path(node.value)):
        path = f"{parent}.{node.attr}"

    return path


def _infer_callable_kind(node: ast.expr) -> Inference:
    kind = OperatorReturnKind.UNKNOWN
    reason = None

    if not (path := _expression_path(node)):
        node_type = type(node).__name__
        reason = f"call {node_type=} is not a supported direct name or attribute path"
    elif path.startswith("itertools."):
        kind = OperatorReturnKind.STREAM
    elif "." in path:
        reason = f"call target {path!r} is not a recognized namespace"
    elif path in _STREAM_CALLS:
        kind = OperatorReturnKind.STREAM
    elif path in _NONSTREAM_CALLS:
        kind = OperatorReturnKind.NONSTREAM
    else:
        reason = f"direct call {path!r} is not in a return-kind whitelist"

    return kind, reason


def _infer_expression_kind(
    node: ast.expr,
    assignments: dict[str, ast.expr],
    seen: frozenset[str] = frozenset(),
) -> Inference:
    kind = OperatorReturnKind.UNKNOWN
    reason = None

    if isinstance(node, ast.Name):
        if node.id in seen:
            reason = f"assignment cycle detected while resolving {node.id!r}"
        elif value := assignments.get(node.id):
            kind, reason = _infer_expression_kind(value, assignments, seen | {node.id})
        else:
            reason = f"returned name {node.id!r} has no supported top-level assignment"
    elif isinstance(node, (ast.Await, ast.NamedExpr)):
        kind, reason = _infer_expression_kind(node.value, assignments, seen)
    elif isinstance(node, ast.GeneratorExp):
        kind = OperatorReturnKind.STREAM
    elif isinstance(node, ast.Call):
        path = _expression_path(node.func)
        is_passthrough = path and path.startswith(_PASSTHROUGH_NAMESPACES)

        if is_passthrough and node.args:
            argument = node.args[0]
            kind, reason = _infer_callable_kind(argument)

            if kind == OperatorReturnKind.UNKNOWN:
                kind, reason = _infer_expression_kind(argument, assignments, seen)
        elif is_passthrough:
            reason = f"passthrough call {path!r} has no positional argument to inspect"
        else:
            kind, reason = _infer_callable_kind(node.func)
    elif isinstance(node, NonstreamExpressions):
        kind = OperatorReturnKind.NONSTREAM
    else:
        reason = f"return expression {type(node).__name__} is not supported"

    return kind, reason


def _infer_unannotated_return_kind(pipe: Pipeline) -> OperatorReturnKind:
    """
    Infer the obvious return kind of a short, unannotated pipe.

    This is an intentionally narrow AST heuristic for doctest pipes.

    Assumptions:

    - Generator and async-generator functions are handled by the caller.
    - The final statement is the only relevant return.
    - Only simple top-level ``name = expression`` assignments are followed.
    - Decorators preserve ``__wrapped__`` with ``functools.wraps``.
    - Source is available through ``inspect.getsource``.
    - Builtins are not shadowed.
    - ``itertools``, ``asyncio``, and ``bado`` are not aliased.
    - Any ``itertools.*`` call returns a stream.
    - Any ``asyncio.*``, ``bado.*``, or ``riko.bado.*`` call passes
      through the result represented by its first positional argument.
    - Arbitrary calls and unsupported expressions are unknown.
    - Runtime validity is not checked.

    Examples:
        >>> def mapped(items):
        ...     return map(str, items)
        >>> _infer_unannotated_return_kind(mapped).value
        'stream'

        >>> def chained(items):
        ...     return itertools.chain(items)
        >>> _infer_unannotated_return_kind(chained).value
        'stream'

        >>> def counted(items):
        ...     return sum(items)
        >>> _infer_unannotated_return_kind(counted).value
        'nonstream'

        >>> async def async_counted(items):
        ...     result = await bado.maybe_deferred(sum, items)
        ...     return result
        >>> _infer_unannotated_return_kind(async_counted).value
        'nonstream'

        >>> async def async_mapped(items):
        ...     result = await asyncio.to_thread(map, str, items)
        ...     return result
        >>> _infer_unannotated_return_kind(async_mapped).value
        'stream'

        >>> def ambiguous(items):
        ...     return build_result(items)
        >>> _infer_unannotated_return_kind(ambiguous).value
        'unknown'

    """
    kind = OperatorReturnKind.UNKNOWN
    reason = None
    name = getattr(pipe, "__qualname__", repr(pipe))
    is_func = lambda node: isinstance(node, (FunctionDef, AsyncFunctionDef))

    try:
        module = ast.parse(textwrap.dedent(getsource(unwrap(pipe))))

        if function := next(builtins.filter(is_func, module.body), None):
            statement = cast_type(FunctionDef, function).body[-1]
    except (OSError, TypeError, SyntaxError, IndexError) as exc:
        exc_type = type(exc).__name__
        reason = f"source could not be inspected or parsed: {exc_type}: {exc}"
    else:
        if function := next(builtins.filter(is_func, module.body), None):
            function = cast_type(FunctionDef | AsyncFunctionDef, function)

            if not function.body:
                reason = "function body is empty"
            elif not isinstance(statement := function.body[-1], ast.Return):
                reason = f"final statement is {type(statement).__name__}, not Return"
            elif statement.value is None:
                kind = OperatorReturnKind.NONSTREAM
            else:
                assignments = {
                    target.id: candidate.value
                    for candidate in function.body[:-1]
                    if isinstance(candidate, ast.Assign)
                    and len(candidate.targets) == 1
                    and isinstance(target := candidate.targets[0], ast.Name)
                }
                kind, reason = _infer_expression_kind(statement.value, assignments)
        else:
            reason = "parsed source contains no function definition"

    if reason and kind == OperatorReturnKind.UNKNOWN:
        logger.debug(f"Could not infer return kind because {name}: {reason}.")
    elif kind == OperatorReturnKind.UNKNOWN:
        logger.debug("Could not infer return kind, but no reason was provided.")

    return kind


def _gen_operator_return_kinds(pipe: Pipeline) -> Iterator[OperatorReturnKind]:
    if isgeneratorfunction(pipe) or isasyncgenfunction(pipe):
        yield OperatorReturnKind.STREAM
    else:
        try:
            annotation = get_type_hints(pipe).get("return")
        except (NameError, TypeError):
            annotation = None

        if annotation:
            for member, candidate in _gen_members(annotation):
                if member in {Any, object}:
                    yield OperatorReturnKind.UNKNOWN
                elif _matches_abc(candidate, Iterator):
                    yield OperatorReturnKind.STREAM
                else:
                    yield OperatorReturnKind.NONSTREAM
        else:
            yield _infer_unannotated_return_kind(pipe)
