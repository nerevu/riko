# vim: sw=4:ts=4:expandtab
"""Provides return-kind inference for operator pipes."""

from __future__ import annotations

import ast
import builtins
import textwrap
from ast import AsyncFunctionDef, FunctionDef
from collections.abc import Awaitable, Coroutine, Iterator
from contextlib import suppress
from functools import lru_cache
from inspect import getsource, isasyncgenfunction, isgeneratorfunction, unwrap
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, NamedTuple, TypeAliasType, get_args, get_origin

from typing_extensions import TypeIs

import riko.types._rss as _rss_module
import riko.types._scalars as _scalars_module
import riko.types._streams as _streams_module
import riko.types._values as _values_module
from riko.base._config import settings
from riko.base._logging import get_logger
from riko.base._typing import gen_union_members, resolve_type_hints
from riko.types._streams import Item, ItemOrValue
from riko.types._values import RikoDict
from riko.types.modules import (
    Inference,
    InferenceSource,
    OperatorReturnKind,
    ReturnInference,
)

if TYPE_CHECKING:
    from logging import Logger

    from riko.types._wrappers import Func

logger: Logger = get_logger(__name__)

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
_HINT_NAMESPACES = (_rss_module, _scalars_module, _values_module, _streams_module)
_ITEM_ALIASES = frozenset({Item, ItemOrValue, RikoDict})

_FIX_HINT = (
    "add an explicit return annotation, e.g. `-> Iterator[Item]` for a stream "
    "or `-> int` for a single value"
)

NonstreamExpressions: tuple[type, ...] = (
    ast.BinOp,
    ast.Compare,
    ast.Constant,
    ast.Dict,
    ast.DictComp,
    ast.JoinedStr,
    ast.Lambda,
    ast.List,
    ast.ListComp,
    ast.Set,
    ast.SetComp,
    ast.Tuple,
    ast.UnaryOp,
)


class AnnotationMember(NamedTuple):
    """
    An annotation arm paired with the type used to classify it.

    ``candidate`` is the arm's ``get_origin`` (``Iterator`` for ``Iterator[Item]``)
    or the arm itself when it has none, so it can be tested against an ABC directly.
    """

    annotation: object
    candidate: object


def _gen_members(annotation: object) -> Iterator[AnnotationMember]:
    """
    Flattens an annotation into the arms that decide its return kind.

    Unions expand to one member per arm; ``Annotated[T, ...]`` and
    ``Awaitable``/``Coroutine`` wrappers collapse to the type that actually
    reaches the caller. The wrapper metadata is dropped and the *last* type
    argument is taken (``Coroutine[Y, S, R]`` and ``Awaitable[R]`` both return
    ``R``). Each member pairs the arm with its ``get_origin`` and falls back to
    the arm itself when it has none.

    Args:

        annotation: The return annotation to decompose.

    Yields:

        One ``AnnotationMember`` per surviving arm; nothing for an empty
        ``Awaitable``/``Coroutine`` with no type argument.

    """
    for arm in gen_union_members(annotation):
        args = get_args(arm)
        origin = get_origin(arm)

        if origin in {Awaitable, Coroutine}:
            if args:
                yield from _gen_members(args[-1])
        else:
            yield AnnotationMember(arm, origin or arm)


def _matches_abc(candidate: object, abc: type) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, abc)


def _expression_path(node: ast.expr) -> str | None:
    """
    Renders a ``Name``/``Attribute`` chain as a dotted path, else ``None``.

    ``None`` flags a call target that is not a plain name or attribute access (a
    subscript, another call), which the callers treat as unclassifiable rather than
    guessing.

    Args:

        node: The call-target expression to render.

    Returns:

        The dotted path (``"itertools.chain"``, ``"map"``), or ``None`` for any
        node that is not a name or attribute chain.

    """
    path = None

    if isinstance(node, ast.Name):
        path = node.id
    elif isinstance(node, ast.Attribute) and (parent := _expression_path(node.value)):
        path = f"{parent}.{node.attr}"

    return path


def _infer_callable_kind(node: ast.expr) -> Inference:
    """
    Classifies a call *target* against the return-kind whitelists.

    Only ``itertools.*`` and the bare-name ``_STREAM_CALLS``/``_NONSTREAM_CALLS``
    builtins are recognized. Anything else; an unknown namespace, a non-whitelisted
    name, or a target with no dotted path; stays ``UNKNOWN`` with a ``reason`` naming
    what defeated it.

    Args:

        node: The call-target expression (a call's ``func``, or a bare argument
            handed through from a passthrough call).

    Returns:

        An ``Inference`` pairing the classified kind with ``None``, or ``UNKNOWN``
        with a ``reason`` when the target is not whitelisted.

    """
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
    node: ast.expr, assignments: dict[str, ast.expr], seen: frozenset[str] = frozenset()
) -> Inference:
    """
    Classifies a ``return`` expression by resolving local names it references.

    A returned ``Name`` is followed to its top-level ``assignments``. ``seen`` guards
    against cycles. Generator expressions are streams; comprehensions and literal
    containers are non-stream. A call through a passthrough namespace
    (``asyncio``/``bado``) is transparent (its first argument is inspected in place of
    the wrapper), otherwise the call target is classified directly.

    Args:

        node: The expression to classify (a function's final return value).
        assignments: Top-level name -> value bindings a returned name may resolve to.

    Kwargs:

        seen: Names already being resolved, used to break assignment cycles.

    Returns:

        An ``Inference`` pairing the classified kind with ``None``, or ``UNKNOWN``
        with a ``reason`` when the expression cannot be classified.

    """
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


def _is_function_def(node: ast.AST) -> TypeIs[FunctionDef | AsyncFunctionDef]:
    return isinstance(node, (FunctionDef, AsyncFunctionDef))


def infer_from_source(pipe: Func[object]) -> ReturnInference:
    """
    Infers the return kind of a short, unannotated pipe from its source.

    A deliberately narrow AST fallback for doctest pipes. Generator and
    async-generator functions are handled by the caller. When the return cannot
    be classified, the result's ``reason`` explains why and how to fix the
    function contract.

    Args:

        pipe: The undecorated pipe function to inspect.

    Returns:

        A ``ReturnInference`` whose ``source`` is ``AST`` on success, or ``None``
        with a populated ``reason`` when the return kind cannot be classified.

    Examples:

        >>> def mapped(items):
        ...     return map(str, items)
        >>>
        >>> infer_from_source(mapped)
        ReturnInference(kind=<...STREAM: 'stream'>, source=<...AST: 'ast'>, reason='')

    """
    kind = OperatorReturnKind.UNKNOWN
    reason = None
    name = getattr(pipe, "__qualname__", repr(pipe))

    try:
        module = ast.parse(textwrap.dedent(getsource(unwrap(pipe))))
    except (OSError, TypeError, SyntaxError, IndexError) as e:
        exc_type = type(e).__name__
        reason = f"source could not be inspected or parsed: {exc_type}: {e}"
    else:
        if function := next(builtins.filter(_is_function_def, module.body), None):
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

    if kind is OperatorReturnKind.UNKNOWN:
        detail = reason or "the return expression could not be classified"
        reason = f"{detail}; {_FIX_HINT}"
        logger.debug(f"Could not infer return kind for {name}: {reason}")
        result = ReturnInference(kind, None, reason)
    else:
        result = ReturnInference(kind, InferenceSource.AST)

    return result


def _resolve_return_hint(pipe: Func[object]) -> object | None:
    """
    Resolves a pipe's return annotation alone, else ``None``.

    Only the return hint is evaluated. A hint naming something imported only for type
    checking cannot make it fail. The item, value, and feed-entry type namespaces are
    supplied so a PEP 563 (``from __future__ import annotations``) return hint like
    ``-> Stream`` still resolves when the module imports those names only under
    ``TYPE_CHECKING``.
    """
    function, annotation = unwrap(pipe), None
    annotations = getattr(function, "__annotations__", {})

    if "return" in annotations:
        hints = {"return": annotations["return"]}
        globalns = getattr(function, "__globals__", {})
        stub = SimpleNamespace(__annotations__=hints, __globals__=globalns)

        with suppress(NameError, TypeError):
            annotation = resolve_type_hints(stub, *_HINT_NAMESPACES).get("return")

    return annotation


def gen_return_inferences(pipe: Func[object]) -> Iterator[ReturnInference]:
    """
    Infers a pipe's return kind using the most reliable evidence.

    A generator or async-generator function is a stream. Any other function is inferred
    from its return annotation. Single item and value aliases (e.g., ``Item``,
    ``ItemOrValue``, ``RikoDict``) are never a stream. With no resolvable return
    annotation, it falls back to ``infer_from_source``'s AST inspection.

    Args:

        pipe: The undecorated pipe function to classify.

    Yields:

        One ``ReturnInference`` per return arm (``UNKNOWN`` for an ``Any``/``object``
        return or a return alias the runtime cannot resolve).

    Examples:

        >>> from collections.abc import Iterator
        >>>
        >>> def dual(items) -> int | Iterator[dict]:
        ...     return items
        >>>
        >>> [inf.kind.value for inf in gen_return_inferences(dual)]
        ['nonstream', 'stream']

    """
    if isgeneratorfunction(pipe) or isasyncgenfunction(pipe):
        yield ReturnInference(OperatorReturnKind.STREAM, InferenceSource.GENERATOR)
    else:
        if annotation := _resolve_return_hint(pipe):
            nonstream_anno = (OperatorReturnKind.NONSTREAM, InferenceSource.ANNOTATION)
            stream_anno = (OperatorReturnKind.STREAM, InferenceSource.ANNOTATION)
            unknown = (OperatorReturnKind.UNKNOWN, None)
            anno_reason = f"return annotation {annotation!r} is too broad to classify; "
            anno_reason += "narrow it to a concrete stream (Iterator[…]) or value type"

            for member, candidate in _gen_members(annotation):
                if member in _ITEM_ALIASES:
                    yield ReturnInference(*nonstream_anno)
                elif member in {Any, object}:
                    yield ReturnInference(*unknown, anno_reason)
                elif isinstance(member, TypeAliasType):
                    reason = f"return annotation alias {member!r} names a type that is "
                    yield ReturnInference(*unknown, reason + "not available at runtime")
                elif _matches_abc(candidate, Iterator):
                    yield ReturnInference(*stream_anno)
                else:
                    yield ReturnInference(*nonstream_anno)
        else:
            yield infer_from_source(pipe)


def gen_operator_return_kinds(pipe: Func[object]) -> Iterator[OperatorReturnKind]:
    """
    Reduces the full inferences to their bare return kinds.

    Use ``gen_return_inferences`` instead when the source or the reason behind an
    unclassifiable kind matters.

    Args:

        pipe: The undecorated pipe function to classify.

    Yields:

        The bare ``OperatorReturnKind`` of each inference.

    Examples:

        >>> def counted(items) -> int:
        ...     return sum(items)
        >>>
        >>> next(map(str, gen_operator_return_kinds(counted)))
        'nonstream'

    """
    for inference in gen_return_inferences(pipe):
        yield inference.kind


@lru_cache(maxsize=settings.return_kinds_cache_size)
def infer_return_kinds(pipe: Func[object]) -> frozenset[OperatorReturnKind]:
    """
    Infers the set of a pipe's bare return kinds, remembered per function.

    The inference reads only the function's definition (its kind, return annotation,
    or source), which never changes once defined.

    Args:

        pipe: The undecorated pipe function to classify.

    Returns:

        Every ``OperatorReturnKind`` the pipe may return.

    Examples:

        >>> def counted(items) -> int:
        ...     return sum(items)
        >>>
        >>> sorted(kind.value for kind in infer_return_kinds(counted))
        ['nonstream']

    """
    return frozenset(gen_operator_return_kinds(pipe))
