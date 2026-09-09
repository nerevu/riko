# vim: sw=4:ts=4:expandtab
"""
riko.modules._inference
~~~~~~~~~~~~~~~~~~~~~~~~

Provides return-kind inference for operator pipes.

Uses annotations, generator detection, and a small AST fallback.
"""

import ast
import builtins
import textwrap
from ast import AsyncFunctionDef, FunctionDef
from collections.abc import Awaitable, Callable, Coroutine, Iterator
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

import pygogo as gogo
from typing_extensions import TypeIs

from riko.types.modules import (
    Inference,
    InferenceSource,
    OperatorReturnKind,
    ReturnInference,
)

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


def _unwrap_alias(annotation: object) -> object:
    """
    Resolves a ``TypeAliasType`` to its value.

    Since an alias may expand to another alias (``type A = B``;
    ``type B = Iterator[Item]``), this loops until it reaches a terminal value.

    Args:
        annotation: The annotation to unwrap; a non-alias passes through.

    Returns:
        The alias's underlying value, or the annotation itself when it is not a
        ``TypeAliasType``.

    """
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__

    return annotation


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


def infer_from_source(pipe: Callable) -> ReturnInference:
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


def gen_return_inferences(pipe: Callable) -> Iterator[ReturnInference]:
    """
    Infers a pipe's return kind using the most reliable evidence.

    A generator or async-generator function is a stream outright. Otherwise the
    return annotation decides: one inference per union arm, ``UNKNOWN`` for an
    ``Any``/``object`` arm too broad to classify. With no annotation, it falls
    back to the AST inspection of ``infer_from_source``.

    Args:
        pipe: The undecorated pipe function to classify.

    Yields:
        One ``ReturnInference`` per considered arm (a single inference for the
        generator and source-fallback paths).

    Examples:
        >>> from collections.abc import Iterator
        >>>
        >>> def gen(items):
        ...     yield from items
        >>>
        >>> [inf.source.value for inf in gen_return_inferences(gen)]
        ['generator']
        >>> def dual(items) -> int | Iterator[dict]:
        ...     return items
        >>>
        >>> [inf.kind.value for inf in gen_return_inferences(dual)]
        ['nonstream', 'stream']

    """
    if isgeneratorfunction(pipe) or isasyncgenfunction(pipe):
        yield ReturnInference(OperatorReturnKind.STREAM, InferenceSource.GENERATOR)
    else:
        try:
            annotation = get_type_hints(pipe).get("return")
        except (NameError, TypeError):
            annotation = None

        if annotation:
            for member, candidate in _gen_members(annotation):
                if member in {Any, object}:
                    reason = (
                        f"return annotation {annotation!r} is too broad to classify; "
                        "narrow it to a concrete stream (Iterator[...]) or value type"
                    )
                    yield ReturnInference(OperatorReturnKind.UNKNOWN, None, reason)
                elif _matches_abc(candidate, Iterator):
                    yield ReturnInference(
                        OperatorReturnKind.STREAM, InferenceSource.ANNOTATION
                    )
                else:
                    yield ReturnInference(
                        OperatorReturnKind.NONSTREAM, InferenceSource.ANNOTATION
                    )
        else:
            yield infer_from_source(pipe)


def gen_operator_return_kinds(pipe: Callable) -> Iterator[OperatorReturnKind]:
    """
    Reduces the full inferences to their bare return kinds.

    The projection ``_derive_operator_subtypes`` (in ``riko.modules._derive``)
    consumes: it needs only the kinds to classify an operator as
    ``aggregator``/``composer``, not where each kind came from.

    Args:
        pipe: The undecorated pipe function to classify.

    Yields:
        The bare ``OperatorReturnKind`` of each inference, in order.

    Examples:
        >>> def counted(items) -> int:
        ...     return sum(items)
        >>>
        >>> [kind.value for kind in gen_operator_return_kinds(counted)]
        ['nonstream']

    """
    for inference in gen_return_inferences(pipe):
        yield inference.kind
