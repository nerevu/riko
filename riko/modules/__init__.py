# vim: sw=4:ts=4:expandtab
"""
riko.modules
~~~~~~~~~~~~
"""

import ast
import builtins
import textwrap
from ast import AsyncFunctionDef, FunctionDef
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from copy import copy
from dataclasses import dataclass
from functools import partial, wraps
from importlib import import_module
from inspect import (
    getsource,
    isasyncgenfunction,
    isawaitable,
    isgeneratorfunction,
    unwrap,
)
from itertools import chain, islice
from pkgutil import iter_modules as iter_package_modules
from types import UnionType
from typing import (
    Annotated,
    Any,
    Literal,
    NamedTuple,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)
from typing import cast as cast_type

import pygogo as gogo

from riko import Context, Objconf, listize, objectify
from riko.bado.itertools import async_map
from riko.cast import CAST_SWITCH, BasicCastType, CastType, cast_none, cast_pass
from riko.cast import cast as cast_value
from riko.dotdict import DotDict, is_mapping
from riko.parsers import conf_is_dynamic, get_field, get_skip, parse_conf
from riko.types.general import (
    AsyncOperatorParser,
    AsyncOperatorWrapper,
    AsyncProcessorParser,
    AsyncProcessorWrapper,
    AsyncSplitterParser,
    AsyncSplitterWrapper,
    Casted,
    CastFuncs,
    Conf,
    Defaults,
    Dispatched,
    Item,
    ItemOrValue,
    ModuleWrapper,
    OperatorParser,
    OperatorParserOutput,
    OperatorWrapper,
    OperatorWrapperInput,
    OperatorWrapperOutput,
    Opts,
    ParseFuncs,
    ParserOutput,
    Pipeline,
    PipeTuples,
    ProcessorParser,
    ProcessorParserOutput,
    ProcessorWrapper,
    ProcessorWrapperInput,
    ProcessorWrapperOutput,
    SplitterParser,
    SplitterWrapper,
    SplitterWrapperInput,
    Stream,
    StreamOrValueStream,
    Streams,
    SyncArgFunc,
    SyncConfCastFunc,
    SyncOperatorParser,
    SyncOperatorWrapper,
    SyncProcessorParser,
    SyncProcessorWrapper,
    SyncSplitterParser,
    SyncSplitterWrapper,
    ValueStream,
)
from riko.types.modules import (
    ConfValues,
    Embed,
    Inference,
    ModuleMetadata,
    ModuleSubtype,
    ModuleSubtypes,
    ModuleType,
    OperatorReturnKind,
)
from riko.types.values import (
    _NONSTREAM_EXPRESSIONS,
    BasicReturn,
    PrimitiveValue,
    StatefulItem,
)
from riko.utils import broadcast, dispatch, parse_context

logger = gogo.Gogo(__name__, monolog=True).logger

SUBTYPES: dict[ModuleSubtype, ModuleType] = {
    "source": "processor",
    "transformer": "processor",
    "splitter": "splitter",
    "composer": "operator",
    "aggregator": "operator",
}

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
    elif isinstance(node, ast.Attribute):
        if parent := _expression_path(node.value):
            path = f"{parent}.{node.attr}"

    return path


def _infer_callable_kind(node: ast.expr) -> Inference:
    kind: OperatorReturnKind = "unknown"
    reason = None

    if not (path := _expression_path(node)):
        node_type = type(node).__name__
        reason = f"call {node_type=} is not a supported direct name or attribute path"
    elif path.startswith("itertools."):
        kind = "stream"
    elif "." in path:
        reason = f"call target {path!r} is not a recognized namespace"
    elif path in _STREAM_CALLS:
        kind = "stream"
    elif path in _NONSTREAM_CALLS:
        kind = "nonstream"
    else:
        reason = f"direct call {path!r} is not in a return-kind whitelist"

    return kind, reason


def _infer_expression_kind(
    node: ast.expr,
    assignments: dict[str, ast.expr],
    seen: frozenset[str] = frozenset(),
) -> Inference:
    kind: OperatorReturnKind = "unknown"
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
        kind = "stream"
    elif isinstance(node, ast.Call):
        path = _expression_path(node.func)
        is_passthrough = path and path.startswith(_PASSTHROUGH_NAMESPACES)

        if is_passthrough and node.args:
            argument = node.args[0]
            kind, reason = _infer_callable_kind(argument)

            if kind == "unknown":
                kind, reason = _infer_expression_kind(argument, assignments, seen)
        elif is_passthrough:
            reason = f"passthrough call {path!r} has no positional argument to inspect"
        else:
            kind, reason = _infer_callable_kind(node.func)
    elif isinstance(node, _NONSTREAM_EXPRESSIONS):
        kind = "nonstream"
    else:
        reason = f"return expression {type(node).__name__} is not supported"

    return kind, reason


def _infer_unannotated_return_kind(pipe: Pipeline) -> OperatorReturnKind:
    """Infer the obvious return kind of a short, unannotated pipe.

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
        >>> _infer_unannotated_return_kind(mapped)
        'stream'

        >>> def chained(items):
        ...     return itertools.chain(items)
        >>> _infer_unannotated_return_kind(chained)
        'stream'

        >>> def counted(items):
        ...     return sum(items)
        >>> _infer_unannotated_return_kind(counted)
        'nonstream'

        >>> async def async_counted(items):
        ...     result = await bado.maybe_deferred(sum, items)
        ...     return result
        >>> _infer_unannotated_return_kind(async_counted)
        'nonstream'

        >>> async def async_mapped(items):
        ...     result = await asyncio.to_thread(map, str, items)
        ...     return result
        >>> _infer_unannotated_return_kind(async_mapped)
        'stream'

        >>> def ambiguous(items):
        ...     return build_result(items)
        >>> _infer_unannotated_return_kind(ambiguous)
        'unknown'
    """
    kind: OperatorReturnKind = "unknown"
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
                kind = "nonstream"
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

    if reason and kind == "unknown":
        logger.debug(f"Could not infer return kind because {name}: {reason}.")
    elif kind == "unknown":
        logger.debug("Could not infer return kind, but no reason was provided.")

    return kind


def _gen_operator_return_kinds(pipe: Pipeline) -> Iterator[OperatorReturnKind]:
    if isgeneratorfunction(pipe) or isasyncgenfunction(pipe):
        yield "stream"
    else:
        try:
            annotation = get_type_hints(pipe).get("return")
        except (NameError, TypeError):
            annotation = None

        if annotation:
            for member, candidate in _gen_members(annotation):
                if member in {Any, object}:
                    yield "unknown"
                elif _matches_abc(candidate, Iterator):
                    yield "stream"
                else:
                    yield "nonstream"
        else:
            yield _infer_unannotated_return_kind(pipe)


def _derive_operator_subtypes(
    pipe: Pipeline,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    subtype: ModuleSubtype | None = None
    subtypes: ModuleSubtypes = set()

    for kind in _gen_operator_return_kinds(pipe):
        if kind == "nonstream":
            subtype = subtype or "aggregator"
            subtypes.add(subtype)
        elif kind == "stream":
            subtype = subtype or "composer"
            subtypes.add("composer")

        if subtype and subtypes == {"aggregator", "composer"}:
            break

    if not subtypes:
        qualified_name = f"{pipe.__module__}.{pipe.__name__}"
        msg = f"{qualified_name} no supported subtypes found"
        raise TypeError(msg)

    return subtype, subtypes


def _derive_loopable(name: str, module_type: ModuleType) -> bool:
    return module_type == "processor" and name != "input"


def _derive_subtypes(
    pipe: Pipeline, module_type: ModuleType, **kwargs
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    if module_type == "processor":
        none_ftype = kwargs.get("ftype") == BasicCastType.NONE
        subtype: ModuleSubtype | None = "source" if none_ftype else "transformer"
        result = subtype, cast_type(ModuleSubtypes, {subtype})
    elif module_type == "splitter":
        result = "splitter", cast_type(ModuleSubtypes, {"splitter"})
    else:
        result = _derive_operator_subtypes(pipe)

    return result


@overload
def _get_subpipe(  # noqa: E704
    embed: SyncProcessorWrapper, context: Context, **embedded_kwargs
) -> partial[ProcessorWrapperOutput]: ...
@overload  # noqa: E302
def _get_subpipe(  # noqa: E704
    embed: AsyncProcessorWrapper, context: Context, **embedded_kwargs
) -> partial[Awaitable[ProcessorWrapperOutput]]: ...
def _get_subpipe(  # noqa: E302 # pyright: ignore[reportInconsistentOverload]
    embed: ProcessorWrapper, context: Context, **embedded_kwargs
) -> partial[ProcessorWrapperOutput | Awaitable[ProcessorWrapperOutput]]:
    embed_context = copy(context)
    embed_context.submodule = True
    embedded_kwargs["context"] = embed_context
    return partial(embed, **embedded_kwargs)


@overload
def get_assignment(  # noqa: E704
    items: Stream | Iterator[StatefulItem] | DotDict, skip: bool = ...
) -> tuple[bool, Stream]: ...
@overload  # noqa: E302
def get_assignment(  # noqa: E704
    items: PrimitiveValue, skip: bool = ...
) -> tuple[bool, ValueStream]: ...
@overload  # noqa: E302
def get_assignment(  # noqa: E704
    items: ProcessorParserOutput | OperatorParserOutput | DotDict, skip: bool = ...
) -> tuple[bool, StreamOrValueStream]: ...
def get_assignment(  # noqa: E302
    items: ProcessorParserOutput | OperatorParserOutput | DotDict,
    skip=False,
    **conf: ConfValues,
) -> tuple[bool, StreamOrValueStream]:
    count = conf.get("count")

    if isinstance(items, Iterator):
        dictized = cast_type(Stream, map(DotDict.dictize, items))
    else:
        dictized = cast_type(StreamOrValueStream, iter([DotDict.dictize(items)]))

    if skip:
        one = False
        result = dictized
    else:
        results = list(islice(dictized, 2))
        multiple = len(results) > 1
        # multiple result pipe, e.g., fetchpage/tokenizer
        # one result pipe, e.g., strconcat

        result = chain(results, dictized) if results else iter(())
        first = bool(count == "first")
        _all = count == "all"
        one = first or not (multiple or _all)

        if one and results:
            result = islice(results, 1)
        elif one:
            result = iter(())

    return one, result


@overload
def gen_assignments[T: StreamOrValueStream](  # noqa: E704
    item: DotDict, assignment: T, assign: str = ..., one: Literal[False] = ...
) -> T: ...
@overload  # noqa: E302
def gen_assignments(  # noqa: E704
    item: DotDict,
    assignment: StreamOrValueStream,
    assign: str = ...,
    *,
    one: Literal[True],
) -> Stream: ...
def gen_assignments(  # noqa: E302
    item: DotDict,
    assignment: Item | StreamOrValueStream,
    assign: str | None = None,
    one=False,
    **_,
) -> Stream:
    if one and isinstance(assignment, Iterator):
        value = next(assignment, None)
    else:
        value = assignment

    value_is_iterator = isinstance(value, Iterator)

    if assign:
        if value is None:
            yield item
        elif item and value_is_iterator:
            yield item | {assign: list(value)}
        elif value_is_iterator:
            yield from ({assign: v} for v in value)
        else:
            yield item | {assign: value}
    elif value_is_iterator:
        yield from map(DotDict.dictize, value)
    else:
        yield DotDict.dictize(value)


def get_pieces_or_conf(
    parsed_conf: object, defaults: Defaults, opts: Opts
) -> tuple[
    BasicReturn | Conf | list[BasicReturn] | Defaults | None,
    Conf | Defaults,
]:
    if is_mapping(parsed_conf):
        merged_conf = cast_type(Conf, {**defaults, **parsed_conf})
    else:
        merged_conf = defaults

    if extract := opts.get("extract"):
        try:
            pieces = next(v for k, v in merged_conf.items() if k.lower() == extract)
        except StopIteration:
            logger.error(f"{extract=} not found in conf {merged_conf}")
            pieces = None
        else:
            pieces = cast_type(BasicReturn, pieces)

        if pieces and opts.get("listize"):
            pieces_or_conf = cast_type(list[BasicReturn], listize(pieces))
        else:
            pieces_or_conf = pieces
    else:
        pieces_or_conf = merged_conf

    return pieces_or_conf, merged_conf


@dataclass(frozen=True)
class PreparedModule:
    name: str
    conf: DotDict
    opts: Opts
    parsers: ParseFuncs
    casters: CastFuncs | None
    assign: str
    emit: bool | Callable[[ParserOutput], bool] | None
    is_source: bool
    static_casted: tuple | None


class Module[B: (Literal[True], Literal[False])]:
    isasync: B

    @overload
    def __init__(  # noqa: E704
        self: "Module[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **opts,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "Module[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **opts,
    ) -> None: ...
    def __init__(  # noqa: E301
        self,
        defaults: Defaults | None = None,
        *,
        isasync=False,
        pollable=False,
        debug=False,
        ftype: BasicCastType = BasicCastType.PASS,
        ptype: BasicCastType = BasicCastType.PASS,
        **opts,
    ):
        # Only called once on pipe import
        self.defaults = defaults or Defaults()
        self._opts = Opts(ftype=ftype, ptype=ptype)
        self._opts.update(cast_type(Opts, opts))
        self.debug = debug
        self.isasync = isasync  # pyright: ignore[reportAttributeAccessIssue]
        self.pollable = pollable
        self.types = set()

    def _set_wrapper_metadata(self, wrapper: wraps, pipe: Pipeline) -> None:
        raw_type = type(self).__name__

        if raw_type not in {"operator", "processor", "splitter"}:
            raise TypeError(f"Unsupported module type: {raw_type!r}")

        module_type = cast_type(ModuleType, raw_type)
        subtype, subtypes = _derive_subtypes(pipe, module_type, **self._opts)
        name = pipe.__module__.rsplit(".", 1)[-1]
        loopable = _derive_loopable(name, module_type)

        setattr(wrapper, "name", name)  # noqa: B010
        setattr(wrapper, "type", module_type)  # noqa: B010
        setattr(wrapper, "subtype", subtype)  # noqa: B010
        setattr(wrapper, "subtypes", subtypes)  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
        setattr(wrapper, "isasync", self.isasync)  # noqa: B010
        setattr(wrapper, "loopable", loopable)  # noqa: B010

    def prepare(
        self,
        module_name: str,
        conf: Conf = None,
        assign: str = "",
        emit: bool | None = None,
        **kwargs,
    ) -> PreparedModule:
        """
        Resolve invocation state into an immutable ``PreparedModule``. Each call
        returns fresh state so concurrent invocations and differing call-site
        options never overwrite one another.

        Examples:
            >>> @processor()
            ... def pipe(item, extraction, objconf, **kwargs):
            ...     return f"{item['content']}-{objconf.times}"
            ...
            >>> item = {'content': 'hi'}
            >>> a = next(pipe(item, conf={'times': '1'}, assign='x'))
            >>> b = next(pipe(item, conf={'times': '2'}, assign='y'))
            >>> (a, b)
            ({'content': 'hi', 'x': 'hi-1'}, {'content': 'hi', 'y': 'hi-2'})

        """
        conf = conf or {}
        def_emit = self._opts.get("emit") if emit is None else emit
        def_assign = assign or self._opts.get("assign", "")
        opts = Opts(self._opts)
        opts.setdefault("objectify", self._opts.get("ptype") != BasicCastType.NONE)

        _type_name = type(self).__name__
        is_source = False

        if _type_name == "operator":
            _emit = is_mapping if def_emit is None else def_emit
            _assign = def_assign or module_name
        elif _type_name in {"processor", "splitter"}:
            is_source = self._opts.get("ftype") == BasicCastType.NONE

            if def_emit is None:
                _emit = is_source or is_mapping
            else:
                _emit = def_emit

            assignment = "content" if is_source else module_name
            _assign = def_assign or assignment
        else:
            logger.error(f"Unknown module {self}.")
            _emit = def_emit
            _assign = def_assign

        module_conf = DotDict(cast_type(dict, self.defaults))
        module_conf.update(cast_type(dict, conf))
        _conf = cast_type(Conf, module_conf.asdict())

        if _emit and assign and not callable(_emit):
            msg = f"Assign is set to {assign} for {module_name} but will be "
            msg += "overridden since emit is True."
            logger.warning(msg)

        opts["emit"] = _emit
        opts["assign"] = _assign
        opts.update(cast_type(Opts, kwargs))
        parsers = get_parsers(opts, conf=_conf, **kwargs)
        static_casted = None

        if opts.get("ptype") == BasicCastType.NONE:
            casters = None
        else:
            casters = get_casters(opts)

            if casters and not isinstance(parsers.conf_parser, partial):
                parsed_conf = parsers.conf_parser({})
                args = (parsed_conf, self.defaults, opts)
                parsed = get_pieces_or_conf(*args)
                casted = dispatch(parsed, *casters[1:])
                static_casted = (casters[0], *casted)

        return PreparedModule(
            name=module_name,
            conf=module_conf,
            opts=opts,
            parsers=parsers,
            casters=casters,
            assign=_assign,
            emit=_emit,
            is_source=is_source,
            static_casted=static_casted,
        )


class processor[B: (Literal[True], Literal[False])](Module):  # noqa: N801
    isasync: B

    @overload
    def __init__(  # noqa: E704
        self: "processor[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "processor[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs,
    ) -> None: ...
    def __init__(self, *args, **kwargs):  # noqa: E301
        """
        Creates a sync/async pipe that processes individual items. These
        pipes are classified as `type: processor` and as either
        `sub_type: transformer` or `subtype: source`. To be recognized as
        `subtype: source`, the pipes `ftype` must be set to 'none'.

        Args:
            defaults (dict): Default `conf` values.
            isasync (bool): Wraps an async pipe (default: False)
            pollable (bool): Pipe returns a callable stream (default: False)
            debug (bool): Print pipe content to stdout (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            conf (dict): The pipe configuration
            extract (str): The key with which to get a value from `conf`. If
                set, the wrapped pipe will receive this value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            objectify (bool): Convert `conf` to a meza.fntools.Objectify
                instance (default: True unless  `ptype` is 'none').

            ptype (str): Used to convert `conf` items to a specific type.
                Performs conversion after obtaining the `objectify` value above.
                If set, objectified `conf` items will be converted upon
                attribute retrieval, and normal `conf` items will be converted
                immediately. Must be one of 'pass', 'none', 'text', 'int', 'float',
                or 'decimal'. Default: 'pass', i.e., return `conf` as is. Note:
                setting to 'none' automatically disables `objectify`.

            field (str): The key with which to get a value from the input
                `item`. If set, the wrapped pipe will receive this value
                instead of `item` (default: None).

            ftype (str): Used to convert the input `item` to a specific type.
                Performs conversion after obtaining the `field` value above.
                If set, the wrapped pipe will receive this value instead of
                `item`. Must be one of 'pass', 'none', 'text', 'int', 'float',
                or 'decimal'. Default: 'pass', i.e., return the item as is.
                Note: setting to 'none' automatically enables `emit`.

            count (str): Stream count. Must be either 'first' (yields only the
                first result) or 'all' (yields all results in a list). Default:
                None (yield all results, but only return a list if there is
                more than one result).

            assign (str): Attribute to assign stream (default: 'content' if
                `ftype` is 'none', pipe name otherwise). Ignored if `emit` is true.

            emit (bool): Return the stream as is and don't assign it to an item
                attribute (default: True if item is a source [`ftype`
                is set to 'none'] or mapping, False otherwise). Overrides `assign`.

            skip_if (func): A function that takes the `item` and should return
                True if processing should be skipped, or False otherwise. If
                processing is skipped, the resulting stream will be the original
                input `item`.

        Examples:
            >>> from riko.bado import react, async_return, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> @processor()
            ... def pipe(item, extraction, objconf, **kwargs):
            ...     content = item['content']
            ...     return f'say "{content}" {objconf.times} times!'
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @processor(isasync=True)
            ... async def async_pipe(item, extraction, objconf, **kwargs):
            ...     content = await async_return(item['content'])
            ...     return f'say "{content}" {objconf.times} times!'
            ...
            >>> item = {'content': 'hello world'}
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> next(pipe(item, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>>
            >>> async def run(reactor):
            ...     result = await async_pipe(item, **kwargs)
            ...     print(next(result))
            ...
            >>> if _issync:
            ...     {'content': 'say "hello world" three times!'}
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            {'content': 'say "hello world" three times!'}

        """
        super().__init__(*args, **kwargs)

    def parse(
        self, item: ProcessorWrapperInput | ItemOrValue, module_name: str
    ) -> DotDict:
        if isinstance(item, Iterator):
            items = list(islice(item, 2))

            if len(items) > 1:
                msg = f"{module_name} received an Iterator of more than 1 item. "
                msg += "Did you forget to use a loop? Processing only the first "
                msg += "item."
                logger.error(msg)

            parsed = self.parse(items[0], module_name) if items else DotDict()
        elif item is None:
            parsed = DotDict()
        elif is_mapping(item):
            parsed = DotDict(item)
        else:
            parsed = DotDict({"content": item})

        return parsed

    def setup(
        self, prepared: PreparedModule, _input: DotDict, **kwargs
    ) -> tuple[DotDict, Casted, bool]:
        skip = get_skip(_input, skip_if=prepared.opts.get("skip_if"))

        if prepared.static_casted:
            field_func, pre_casted_extract, pre_casted_conf = prepared.static_casted
            field = kwargs.pop("field", None) or prepared.opts.get("field") or ""
            parsed_field = get_field(_input, field=field, **kwargs)
            casted_field = field_func(parsed_field)
            orig_item = _input
            casted = Casted(casted_field, pre_casted_extract, pre_casted_conf)
        else:
            conf = cast_type(Conf, prepared.conf.asdict())
            args = (_input, prepared.opts, conf)
            orig_item, casted = _dispatch(
                *args,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=Defaults(self.defaults),
                **kwargs,
            )

        return orig_item, casted, skip

    @overload
    def process(  # noqa: E704
        self,
        _input: DotDict,
        stream: Stream | DotDict,
        assign: str,
        emit: bool = ...,
        skip: bool = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict,
        stream: ProcessorParserOutput,
        assign: str,
        emit: Literal[False] = ...,
        skip: Literal[False] = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict,
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        skip: Literal[False] = ...,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict,
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[False] = ...,
        *,
        skip: Literal[True],
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict,
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        skip: Literal[True],
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict,
        stream: ProcessorParserOutput,
        assign: str,
        emit: bool = ...,
        skip: bool = ...,
    ) -> ProcessorWrapperOutput: ...
    def process(  # noqa: E301
        self,
        _input: DotDict,
        stream: ProcessorParserOutput,
        assign: str,
        emit: bool = False,
        skip: bool = False,
        **conf: ConfValues,
    ) -> Stream:
        if skip or emit:
            _, result = get_assignment(stream, skip=skip, **conf)
        else:
            one, assignment = get_assignment(stream, skip=False, **conf)
            result = gen_assignments(_input, assignment, assign=assign, one=one)

        return result

    @overload
    def __call__(  # noqa: E704
        self: "processor[Literal[True]]", pipe: AsyncProcessorParser
    ) -> AsyncProcessorWrapper: ...
    @overload  # noqa: E301
    def __call__(  # noqa: E704
        self: "processor[Literal[False]]", pipe: SyncProcessorParser
    ) -> SyncProcessorWrapper: ...
    def __call__(self, pipe: ProcessorParser) -> ProcessorWrapper:  # noqa: E301
        """
        Creates a sync/async pipe that processes individual items

        Args:
            pipe (func): A function of 2 args (content, objconf)
                and a `**kwargs`. TODO: document args & kwargs.

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from riko.bado import react, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> kwargs = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'emit': True, 'field': 'content', 'objectify': False}
            ...
            >>> @processor(**kwargs)
            ... def pipe(content, times, objconf, **kwargs):
            ...     return f'say "{content}" {times[0]} times!'
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @processor(isasync=True, **kwargs)
            ... def async_pipe(content, times, objconf, **kwargs):
            ...     return f'say "{content}" {times[0]} times!'
            ...
            >>> item = {'content': 'hello world'}
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> next(pipe(item, **kwargs))
            'say "hello world" three times!'
            >>>
            >>> async def run(reactor):
            ...     result = await async_pipe(item, **kwargs)
            ...     print(next(result))
            ...
            >>> if _issync:
            ...     {'content': 'say "hello world" three times!'}
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            say "hello world" three times!

        """
        module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            item: ProcessorWrapperInput | None = None,
            conf: Conf = None,
            **kwargs,
        ) -> ProcessorWrapperOutput:
            _input = self.parse(item, module_name)
            prepared = self.prepare(module_name, conf=conf, **kwargs)
            assign = prepared.assign
            orig_item, casted, skip = self.setup(prepared, _input, **kwargs)

            if prepared.static_casted:
                _conf = cast_type(dict[str, ConfValues], prepared.static_casted[2])
            else:
                _conf = cast_type(dict[str, ConfValues], prepared.conf.asdict())

            if skip:
                args = (_input, orig_item, assign)
                processed = self.process(*args, emit=True, skip=True, **_conf)
            else:
                aync_pipe = cast_type(AsyncProcessorParser, pipe)
                context = parse_context(**kwargs)
                kwargs["inputs"] = context.inputs
                result = aync_pipe(*casted, **kwargs)
                stream = (await result) if isawaitable(result) else result
                args = (_input, stream, assign)

                if callable(prepared.emit) and not isinstance(stream, Iterator):
                    emit = prepared.emit(stream)
                else:
                    emit = bool(prepared.emit)

                if emit:
                    processed = self.process(*args, emit=True, skip=False, **_conf)
                else:
                    processed = self.process(*args, emit=False, skip=False, **_conf)

            return processed

        def sync_wrapper(
            item: ProcessorWrapperInput | None = None,
            conf: Conf = None,
            **kwargs,
        ) -> ProcessorWrapperOutput:
            _input = self.parse(item, module_name)
            prepared = self.prepare(module_name, conf=conf, **kwargs)
            assign = prepared.assign
            orig_item, casted, skip = self.setup(prepared, _input, **kwargs)

            if prepared.static_casted:
                _conf = cast_type(dict[str, ConfValues], prepared.static_casted[2])
            else:
                _conf = cast_type(dict[str, ConfValues], prepared.conf.asdict())

            if skip:
                args = (_input, orig_item, assign)
                processed = self.process(*args, emit=True, skip=True, **_conf)
            else:
                sync_pipe = cast_type(SyncProcessorParser, pipe)
                context = parse_context(**kwargs)
                kwargs["inputs"] = context.inputs
                stream = sync_pipe(*casted, **kwargs)
                args = (_input, stream, assign)

                if callable(prepared.emit) and not isinstance(stream, Iterator):
                    emit = prepared.emit(stream)
                else:
                    emit = bool(prepared.emit)

                if emit:
                    processed = self.process(*args, emit=True, skip=False, **_conf)
                else:
                    processed = self.process(*args, emit=False, skip=False, **_conf)

            yield from processed

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe)
        return cast_type(ProcessorWrapper, wrapper)


class operator[B: (Literal[True], Literal[False])](Module):  # noqa: N801
    isasync: B

    @overload
    def __init__(  # noqa: E704
        self: "operator[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "operator[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs,
    ) -> None: ...
    def __init__(self, *args, **kwargs):  # noqa: E301
        """
        Creates a sync/async pipe that processes an entire stream of items

        Args:
            defaults (dict): Default `conf` values.
            isasync (bool): Wraps an async pipe (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            conf (dict): The pipe configuration. May contain key embed.
                embed (dict): Must have key "type". May have key "conf",

            extract (str): The key with which to get values from `conf`. If set,
                the wrapped pipe will receive these value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            objectify (bool): Convert `conf` to a meza.fntools.Objectify
                instance (default: True unless  `ptype` is 'none').

            ptype (str): Used to convert `conf` items to a specific type.
                Performs conversion after obtaining the `objectify` value above.
                If set, objectified `conf` items will be converted upon
                attribute retrieval, and normal `conf` items will be converted
                immediately. Must be one of 'pass', 'none', 'text', 'int', 'float',
                or 'decimal'. Default: 'pass', i.e., return `conf` as is. Note:
                setting to 'none' automatically disables `objectify`.

            field (str): The key with which to get values from the input
                `items`. If set, the wrapped pipe will receive these values
                instead of `items` (default: None).

            ftype (str): Used to convert the input `items` to a specific type.
                Performs conversion after obtaining the `field` values above.
                If set, the wrapped pipe will receive these values instead of
                `items`. Must be one of 'pass', 'none', 'text', 'int', 'float',
                or 'decimal' (default: 'pass', i.e., return the item as is)

            count (str): Stream count. Must be either 'first' (yields only the
                first result) or 'all' (yields all results in a list). Default:
                None (yield all results, but only return a list if there is
                more than one result).

            assign (str): Attribute to assign stream (default: the pipe name). Ignored
                if `emit` is true.

            embed (dict): Must have key "type". May have key "conf",
            emit (bool): return the stream as is and don't assign it to an item
                attribute (default: True if item is a mapping, False otherwise).
                Overrides `assign`.

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from riko.bado import react, async_return, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> # emit is True by default
            >>> # and operators can't skip items, so the pipe is passed an
            >>> # item dependent version of objconf as the 3rd arg
            >>> @operator(emit=False)
            ... def pipe1(stream, objconf, tuples, **kwargs):
            ...     for item, objconf in tuples:
            ...         s = 'say "{content}" {0} times!'
            ...         yield s.format(objconf.times, **item)
            ...
            >>> @operator(emit=False)
            ... def pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item['content'].split()) for item in stream)
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @operator(isasync=True, emit=False)
            ... async def async_pipe1(stream, objconf, tuples, **kwargs):
            ...     item, objconf = next(tuples)
            ...     content = await async_return(item['content'])
            ...     return f'say "{content}" {objconf.times} times!'
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @operator(isasync=True, emit=False)
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item['content'].split()) for item in stream)
            ...
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> conf = {'times': 'three'}
            >>> kwargs = {'conf': conf, 'assign': 'content', 'emit': False}
            >>> next(pipe1(items, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>> next(pipe2(items, **kwargs))
            {'content': 4}
            >>>
            >>> async def run(reactor):
            ...     r1 = await async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = await async_pipe2(items, **kwargs)
            ...     print(next(r2))
            ...
            >>> if _issync:
            ...     {'content': 'say "hello world" three times!'}
            ...     {'content': 4}
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        super().__init__(*args, **kwargs)

    def parse(self, items: OperatorWrapperInput | None = None) -> Stream:
        for item in items or []:
            if is_mapping(item):
                yield cast_type(Item, DotDict(item))
            else:
                yield cast_type(Item, DotDict({"content": item}))

    def setup(
        self, prepared: PreparedModule, _input: Stream, **kwargs
    ) -> tuple[PipeTuples, Stream, Casted]:
        if prepared.static_casted:
            _, pre_casted_extract, pre_casted_conf = prepared.static_casted
            objconf = cast_type(Objconf, pre_casted_conf)
            casted = Casted({}, pre_casted_extract, pre_casted_conf)
            tuples = ((item, objconf) for item in _input)
            orig_stream = _input
        else:
            conf = cast_type(Conf, prepared.conf.asdict())
            _dispatcher = partial(
                _dispatch,
                conf=conf,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=Defaults(self.defaults),
            )
            # Parses conf that can vary per item. Can't handle terminal input
            dispatcher = cast_type(Callable[[Item, Opts], Dispatched], _dispatcher)
            dispatches = (dispatcher(item, prepared.opts) for item in _input)

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and full objconf
            tuples = ((d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches)

            # Parses conf that doesn't vary per item and may contain terminal input
            orig_stream = (d.item for d in dispatches)
            casted = dispatcher(DotDict(), prepared.opts, **kwargs).casted

        return (tuples, orig_stream, casted)

    @overload
    def process(  # noqa: E704
        self,
        stream: Stream | Iterator[StatefulItem],
        assign: str,
        emit: bool = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: Literal[False] = ...,
        **conf: ConfValues,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        **conf: ConfValues,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: bool = ...,
        **conf: ConfValues,
    ) -> OperatorWrapperOutput: ...
    def process(  # noqa: E301
        self,
        stream: ProcessorParserOutput | OperatorParserOutput,
        assign: str,
        emit: bool = False,
        **conf: ConfValues,
    ) -> OperatorWrapperOutput:
        one, assignment = get_assignment(stream, skip=False, **conf)

        if emit:
            result = assignment
        else:
            result = gen_assignments(DotDict(), assignment, assign=assign, one=one)

        return result

    @overload
    def __call__(  # noqa: E704
        self: "operator[Literal[True]]", pipe: AsyncOperatorParser
    ) -> AsyncOperatorWrapper: ...
    @overload  # noqa: E301
    def __call__(  # noqa: E704
        self: "operator[Literal[False]]", pipe: SyncOperatorParser
    ) -> SyncOperatorWrapper: ...
    def __call__(self, pipe: OperatorParser) -> OperatorWrapper:  # noqa: E301
        """
        Creates a wrapper that allows a sync/async pipe to processes a
        stream of items

        Args:
            pipe (func): A function of 3 args (stream, objconf, tuples)
                and a `**kwargs`. TODO: document args & kwargs.

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from riko import bado
            >>> from riko.bado import react, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> opts = {
            ...     'ftype': 'text', 'extract': 'times', 'listize': True,
            ...     'field': 'content', 'objectify': False
            ... }
            >>> wrapper = operator(**opts)
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> conf = {'times': 'three'}
            >>> kwargs = {'conf': conf, 'assign': 'content', 'emit': False}
            >>>
            >>> def pipe1(stream, times, tuples, **kwargs):
            ...     for content, objconf in tuples:
            ...         yield 'say "{content}" {0} times!'.format(*times, **content)
            ...
            >>> wrapped_pipe1 = wrapper(pipe1)
            >>> next(wrapped_pipe1(items, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>>
            >>> def pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item['content'].split()) for item in stream)
            ...
            >>> wrapped_pipe2 = wrapper(pipe2)
            >>>
            >>> next(wrapped_pipe2(items, **kwargs))
            {'content': 4}
            >>> async_wrapper = operator(isasync=True, **opts)
            >>>
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> def async_pipe1(stream, times, tuples, **kwargs):
            ...     for content, objconf in tuples:
            ...         yield 'say "{content}" {0} times!'.format(*times, **content)
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> async def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     words = (len(item['content'].split()) for item in stream)
            ...     word_cnt = await bado.maybe_deferred(sum, words)
            ...     return word_cnt
            ...
            >>> wrapped_async_pipe1 = async_wrapper(async_pipe1)
            >>> wrapped_async_pipe2 = async_wrapper(async_pipe2)
            >>>
            >>> async def run(reactor):
            ...     r1 = await wrapped_async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = await wrapped_async_pipe2(items, **kwargs)
            ...     print(next(r2))
            ...
            >>> if _issync:
            ...     {'content': 'say "hello world" three times!'}
            ...     {'content': 4}
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        op_module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            items: OperatorWrapperInput | None = None,
            conf: Conf = None,
            context: Context | None = None,
            embed: ProcessorWrapper | None = None,
            **kwargs,
        ) -> OperatorWrapperOutput:
            _input = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, **kwargs)
            _conf = cast_type(dict[str, ConfValues], prepared.conf.asdict())
            assign = prepared.assign
            embedded_kwargs = cast_type(Embed, prepared.conf.pop("embed", None))
            context = parse_context(context, **kwargs)
            kwargs["inputs"] = context.inputs
            stream = cast_type(OperatorWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(prepared, stream, **kwargs)
            embed_type = getattr(embed, "type", None)

            if embed and embed_type and embed.loopable:
                embed = cast_type(AsyncProcessorWrapper, embed)
                embedder = _get_subpipe(embed, context, **embedded_kwargs)
                stream_map = await async_map(embedder, _input)
                stream = cast_type(
                    ProcessorParserOutput, chain.from_iterable(stream_map)
                )
            elif embed and embed_type:
                logger.error(f"{embed.name} is not loopable and can't be embedded.")
            elif embed and callable(embed):
                if name := getattr(embed, "__name__", None):
                    logger.error(f"{name} is a custom pipe and can't be embedded.")
                else:
                    logger.error("Custom embedded pipes are not currently supported.")
            elif op_module_name == "loop":
                logger.error("No embedded pipe provided!")
            else:
                async_pipe = cast_type(AsyncOperatorParser, pipe)
                result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
                stream = (await result) if isawaitable(result) else result

            if isinstance(stream, Iterator):
                emit = bool(prepared.emit)
            elif callable(prepared.emit):
                emit = prepared.emit(stream)
            else:
                emit = bool(prepared.emit)

            if emit:
                processed = self.process(stream, assign, emit=True, **_conf)
            else:
                processed = self.process(stream, assign, emit=False, **_conf)

            return processed

        def sync_wrapper(
            items: OperatorWrapperInput | None = None,
            conf: Conf = None,
            context: Context | None = None,
            embed: ProcessorWrapper | None = None,
            **kwargs,
        ) -> OperatorWrapperOutput:
            _input = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, **kwargs)
            _conf = cast_type(dict[str, ConfValues], prepared.conf.asdict())
            assign = prepared.assign
            embedded_kwargs = cast_type(Embed, prepared.conf.pop("embed", None))
            context = parse_context(context, **kwargs)
            kwargs["inputs"] = context.inputs
            stream = cast_type(OperatorWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(prepared, stream, **kwargs)
            embed_type = getattr(embed, "type", None)

            if embed and embed_type and embed.loopable:
                embed = cast_type(SyncProcessorWrapper, embed)
                embedder = _get_subpipe(embed, context, **embedded_kwargs)
                stream_map = map(embedder, _input)
                stream = cast_type(
                    ProcessorParserOutput, chain.from_iterable(stream_map)
                )
            elif embed_type:
                logger.error(f"{embed.name} is not loopable and can't be embedded.")
            elif embed and callable(embed):
                if name := getattr(embed, "__name__", None):
                    logger.error(f"{name} is a custom pipe and can't be embedded.")
                else:
                    logger.error("Custom embedded pipes are not currently supported.")
            elif op_module_name == "loop":
                logger.error("No embedded pipe provided!")
            else:
                sync_pipe = cast_type(SyncOperatorParser, pipe)
                stream = sync_pipe(orig_stream, casted.extraction, tuples, **kwargs)

            if isinstance(stream, Iterator):
                emit = bool(prepared.emit)
            elif callable(prepared.emit):
                emit = prepared.emit(stream)
            else:
                emit = bool(prepared.emit)

            if emit:
                processed = self.process(stream, assign, emit=True, **_conf)
            else:
                processed = self.process(stream, assign, emit=False, **_conf)

            yield from processed

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe)
        return cast_type(OperatorWrapper, wrapper)


class splitter[B: (Literal[True], Literal[False])](Module):  # noqa: N801
    isasync: B

    @overload
    def __init__(  # noqa: E704
        self: "splitter[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "splitter[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs,
    ) -> None: ...
    def __init__(self, *args, **kwargs):  # noqa: E301
        """
        Creates a sync/async pipe that splits an entire stream of items
        """
        super().__init__(*args, **kwargs)

    def parse(self, items: SplitterWrapperInput | None = None) -> Stream:
        for item in items or []:
            if is_mapping(item):
                yield cast_type(Item, DotDict(item))
            else:
                yield cast_type(Item, DotDict({"content": item}))

    def setup(
        self, prepared: PreparedModule, _input: Stream, **kwargs
    ) -> tuple[PipeTuples, Stream, Casted]:
        conf = cast_type(Conf, prepared.conf.asdict())
        _dispatcher = partial(
            _dispatch,
            conf=conf,
            parsers=prepared.parsers,
            casters=prepared.casters,
            defaults=Defaults(self.defaults),
        )
        dispatcher = cast_type(Callable[[Item, Opts], Dispatched], _dispatcher)
        dispatches = (dispatcher(item, prepared.opts) for item in _input)
        tuples = ((d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches)
        orig_stream = (d.item for d in dispatches)
        casted = dispatcher(DotDict(), prepared.opts, **kwargs).casted
        return (tuples, orig_stream, casted)

    @overload
    def __call__(  # noqa: E704
        self: "splitter[Literal[True]]", pipe: AsyncSplitterParser
    ) -> AsyncSplitterWrapper: ...
    @overload  # noqa: E301
    def __call__(  # noqa: E704
        self: "splitter[Literal[False]]", pipe: SyncSplitterParser
    ) -> SyncSplitterWrapper: ...
    def __call__(self, pipe: SplitterParser) -> SplitterWrapper:  # noqa: E301
        op_module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            items: SplitterWrapperInput | None = None,
            conf: Conf = None,
            **kwargs,
        ) -> Streams:
            _input = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, **kwargs)
            stream = cast_type(SplitterWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(prepared, stream, **kwargs)
            async_pipe = cast_type(AsyncSplitterParser, pipe)
            result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            return (await result) if isawaitable(result) else result

        def sync_wrapper(
            items: SplitterWrapperInput | None = None,
            conf: Conf = None,
            **kwargs,
        ) -> Streams:
            _input = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, **kwargs)
            stream = cast_type(SplitterWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(prepared, stream, **kwargs)
            sync_pipe = cast_type(SyncSplitterParser, pipe)
            streams = sync_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            yield from streams

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe)
        return cast_type(SplitterWrapper, wrapper)


def _dispatch(
    item: Item,
    opts: Opts,
    conf: Conf,
    parsers: ParseFuncs | None = None,
    casters: CastFuncs | None = None,
    defaults: Defaults | None = None,
    field: str | None = None,
    **kwargs,
) -> Dispatched:
    defaults = defaults or Defaults({})
    field = field or opts.get("field")

    if parsers:
        parsed_field, parsed_conf = broadcast(item, *parsers, field=field, **kwargs)
    else:
        parsed_field, parsed_conf = item, conf

    pieces_or_conf, merged_conf = get_pieces_or_conf(parsed_conf, defaults, opts)
    parsed = (parsed_field, pieces_or_conf, merged_conf)
    casted = dispatch(parsed, *casters) if casters else parsed
    conf = cast_type(Conf, casted[2])
    return Dispatched(item, Casted(casted[0], casted[1], conf))


def get_parsers(opts: Opts, conf: Conf, **kwargs) -> ParseFuncs:
    conf = conf or {}

    if opts.get("ftype") == BasicCastType.NONE:
        field_parser = cast_none
    else:
        field_parser = partial(get_field)

    if opts.get("ptype") == BasicCastType.NONE:
        conf_parser = cast_none
    elif conf_is_dynamic(conf, **kwargs):
        conf_parser = partial(parse_conf, conf=conf, memoize=False)
    else:
        pre_parsed = parse_conf(None, conf=conf, memoize=True)
        conf_parser = lambda _, **__: pre_parsed

    return ParseFuncs(field_parser, conf_parser)


def get_casters(opts: Opts) -> CastFuncs:
    ftype = opts.get("ftype")
    ptype = opts.get("ptype")
    extract = opts.get("extract")

    if ftype in CAST_SWITCH:
        _field_func = partial(cast_value, _type=CastType(ftype))
    else:
        if ftype:
            logger.warning(f"Invalid cast {ftype=}. Ignoring.")

        _field_func = cast_pass

    field_func = cast_type(SyncArgFunc, _field_func)

    if ptype in CAST_SWITCH:
        _caster = partial(cast_value, _type=CastType(ptype))
    else:
        if ptype:
            logger.warning(f"Invalid cast {ptype=}. Ignoring.")

        _caster = cast_pass

    caster = cast_type(SyncArgFunc, _caster)

    if ptype == BasicCastType.NONE:
        extract_caster = cast_none
        _conf_caster = cast_pass
    elif opts.get("listize") and opts.get("objectify"):
        extract_caster = lambda pieces: [objectify(piece, caster) for piece in pieces]
        _conf_caster = objectify
    elif opts.get("objectify"):
        extract_caster = partial(objectify, func=caster)
        _conf_caster = objectify if extract else partial(objectify, func=caster)
    else:
        extract_caster = caster
        _conf_caster = cast_pass

    conf_caster = cast_type(SyncConfCastFunc, _conf_caster)
    return CastFuncs(field_func, extract_caster, conf_caster)


def _get_module_metadata(name: str) -> ModuleMetadata | None:
    module = import_module(f"{__name__}.{name}")
    pipes = (getattr(module, target, None) for target in ("pipe", "async_pipe"))
    targets = tuple(cast_type(ModuleWrapper, pipe) for pipe in pipes if callable(pipe))
    attrs = ("name", "type", "subtype", "subtypes", "pollable", "loopable")

    if len(targets) == 2:
        for attr in attrs:
            actual = getattr(targets[0], attr)
            expected = getattr(targets[1], attr)

            if actual != expected:
                msg = f"{module.__name__} has inconsistent sync/async metadata: "
                msg += f"{expected!r} != {actual!r}"
                raise TypeError(msg)

    if targets:
        first = targets[0]

        if first.name != name:
            raise TypeError(f"{module.__name__} reports module name {first.name!r}")

        for subtype in first.subtypes:
            expected_type = SUBTYPES[subtype]

            if first.type != expected_type:
                msg = f"{module.__name__} supports subtype {subtype!r}, "
                msg += f"which requires type {expected_type!r}, not {first.type!r}"
                raise TypeError(msg)

        metadata = ModuleMetadata(
            name=name,
            type=first.type,
            subtype=first.subtype,
            subtypes=first.subtypes,
            pollable=any(t.pollable for t in targets),
            loopable=any(t.loopable for t in targets),
            has_sync=any(not t.isasync for t in targets),
            has_async=any(t.isasync for t in targets),
        )
    else:
        metadata = None

    return metadata


def gen_module_catalog() -> Iterator[ModuleMetadata]:
    for info in iter_package_modules(__path__):
        skip = info.ispkg or info.name.startswith("_")

        if not skip and (metadata := _get_module_metadata(info.name)):
            yield metadata


def _matches_subtype(
    module: ModuleMetadata, subtype: ModuleSubtype | None, *, primary: bool
) -> bool:
    if subtype is None:
        matched = True
    elif primary:
        matched = module.subtype == subtype
    else:
        matched = subtype in module.subtypes

    return matched


@overload
def list_modules(  # noqa: E704
    *,
    type: ModuleType | None = ...,  # noqa: A002
    subtype: ModuleSubtype | None = ...,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[False] = ...,
) -> tuple[str, ...]: ...
@overload  # noqa: E302
def list_modules(  # noqa: E704
    *,
    type: ModuleType | None = None,  # noqa: A002
    subtype: ModuleSubtype | None = None,
    primary: bool = ...,
    loopable: bool | None = ...,
    show_metadata: Literal[True],
) -> tuple[ModuleMetadata, ...]: ...
def list_modules(  # noqa: E302
    *,
    type: ModuleType | None = None,  # noqa: A002
    subtype: ModuleSubtype | None = None,
    primary: bool = False,
    loopable: bool | None = None,
    show_metadata: bool = False,
) -> tuple[str, ...] | tuple[ModuleMetadata, ...]:
    if type and subtype:
        raise ValueError("type and subtype cannot be combined")
    elif primary and not subtype:
        raise ValueError("primary=True requires subtype")

    subtype_match = partial(_matches_subtype, subtype=subtype, primary=primary)
    type_match = lambda module: type is None or module.type == type
    loop_match = lambda module: loopable is None or module.loopable is loopable
    match = lambda module: all(broadcast(module, subtype_match, type_match, loop_match))
    # dynamic filter pipe import shadows the builtin filter
    filtered = builtins.filter(match, gen_module_catalog())
    modules = tuple(sorted(filtered, key=lambda module: module.name))
    return modules if show_metadata else tuple(module.name for module in modules)


__all__ = [
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "list_modules",
    "operator",
    "processor",
    "splitter",
]
