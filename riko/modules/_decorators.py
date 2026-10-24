# vim: sw=4:ts=4:expandtab
"""
Provides decorators for creating processor, operator, and splitter pipes.

Examples:

    Basic usage::

        >>> from riko.ext import DynamicConf, processor
        >>>
        >>> @processor
        ... def pipe(item, extraction, objconf, **kwargs) -> int:
        ...     return item * objconf.times
        >>>
        >>> conf = DynamicConf({"times": 2})
        >>> next(pipe({"x": 3}, conf=conf, field="x", assign="doubled"))
        {'x': 3, 'doubled': 6}

"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterator
from contextlib import aclosing
from functools import partial, wraps
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    NamedTuple,
    Unpack,
    cast,
    overload,
)

from attrs import define

from riko.bado._util import as_awaitable
from riko.bado.itertools import (
    alist,
    as_async,
    async_iter,
    async_map,
    async_map_ordered_stream,
)
from riko.base._guards import (
    is_async_callable,
    is_known_sequence,
    is_listlike,
    is_mapping,
    is_streamlike,
)
from riko.base._logging import get_logger
from riko.base._require_guards import require_from_typed_dict, typed_dict_keys
from riko.definitions._context import Context
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.parsing._dotdict import DotDict
from riko.parsing.config import get_field, get_skip
from riko.types._enums import BasicCastType
from riko.types._io import is_async_closeable
from riko.types._options import (
    Casted,
    ContextOverrides,
    DecorationOptions,
    Defaults,
    OperatorDecorationOptions,
    ProcessorDecorationOptions,
    RawCallOptions,
    SharedDecorationOptions,
    build_require_raw_call_options,
)
from riko.types._pipedef import CountValues, EmbedKwargs
from riko.types._streams import (
    AnyIterable,
    AsyncItemsOrValues,
    AsyncStream,
    Item,
    ItemOrValue,
    Stream,
    StreamOrValueStream,
)
from riko.types._wrappers import PreparedCall
from riko.types.modules import Conf, require_conf

from ._assignment import build_assignment, gen_assignments
from ._derive import get_module_subtypes, has_sequential_inputs, is_loopable
from ._loop import loop_embed_async, loop_embed_sync
from ._prepare import PreparedModule, resolve_and_cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Iterable, Mapping
    from logging import Logger

    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types._values import RikoValue
    from riko.types._wrappers import (
        AsyncOperatorParser,
        AsyncOperatorWrapper,
        AsyncOperatorWrapperInput,
        AsyncOperatorWrapperInternalOutput,
        AsyncOperatorWrapperOutput,
        AsyncPipeTuples,
        AsyncProcessorParser,
        AsyncProcessorWrapper,
        AsyncProcessorWrapperInput,
        AsyncProcessorWrapperInternalOutput,
        AsyncProcessorWrapperOutput,
        AsyncSplitterParser,
        AsyncSplitterWrapper,
        AsyncSplitterWrapperInput,
        AsyncSplitterWrapperOutput,
        AsyncSubPipe,
        AwaitableOperatorParser,
        AwaitableProcessorParser,
        AwaitableSplitterParser,
        ExtraName,
        ItemDispatcher,
        ModuleParser,
        ModuleWrapper,
        OperatorParser,
        OperatorParserOutput,
        OperatorWrapper,
        PipeTuples,
        PrepareConf,
        ProcessorParser,
        ProcessorParserOutput,
        ProcessorWrapper,
        ProcessorWrapperInput,
        SplitterParser,
        SplitterWrapper,
        SplitterWrapperInput,
        SplitterWrapperOutput,
        SyncOperatorParser,
        SyncOperatorWrapper,
        SyncOperatorWrapperInput,
        SyncOperatorWrapperInternalOutput,
        SyncOperatorWrapperOutput,
        SyncPipeTuples,
        SyncProcessorParser,
        SyncProcessorWrapper,
        SyncProcessorWrapperInput,
        SyncProcessorWrapperInternalOutput,
        SyncProcessorWrapperOutput,
        SyncSplitterParser,
        SyncSplitterWrapper,
        SyncSplitterWrapperInput,
        SyncSplitterWrapperOutput,
        SyncSubPipe,
        WrapperOutput,
    )
    from riko.types.modules import ModuleType

logger: Logger = get_logger(__name__)

type AsyncItemProcessor = Callable[
    [ItemOrValue], Awaitable[SyncProcessorWrapperInternalOutput]
]

_SPLITTER_OPTS: frozenset[str] = frozenset(
    SharedDecorationOptions.__required_keys__
    | SharedDecorationOptions.__optional_keys__
)
_OPERATOR_OPTS: frozenset[str] = frozenset(
    OperatorDecorationOptions.__required_keys__
    | OperatorDecorationOptions.__optional_keys__
)
_PROCESSOR_OPTS: frozenset[str] = frozenset(
    ProcessorDecorationOptions.__required_keys__
    | ProcessorDecorationOptions.__optional_keys__
)
_CALL_OPTS: frozenset[str] = frozenset().union(*typed_dict_keys(RawCallOptions))
_CONTEXT_OPTS: frozenset[str] = frozenset().union(*typed_dict_keys(ContextOverrides))
_SPLITTER_CALL_OPTS: frozenset[str] = _CALL_OPTS - {"count"}
_require_call_options = build_require_raw_call_options(error=TypeError)
_require_overrides = require_from_typed_dict(ContextOverrides, error=TypeError)


def _resolve_context(
    context: Context | None, **overrides: Unpack[ContextOverrides]
) -> Context:
    """Derives the context a pipe call runs under from the caller's and overrides."""
    base = Context() if context is None else context
    return base.replace(**overrides)


class _AsyncWrapperStream[T]:
    """
    Dual-protocol result of an async ``processor``/``splitter`` wrapper.

    Async-iterating or ``anext``-ing it consumes the wrapped parser's stream item
    by item with no outer await (the default ``async for item in async_pipe(...)``
    path); awaiting it runs the parser and returns the whole stream (the advanced
    ``await async_pipe(...)`` path). The parser runs once, on first consumption.

    Attributes:

        make: A thunk that invokes the wrapped parser and returns its awaitable
            stream.

    """

    __slots__ = ("_agen", "_make")

    def __init__(self, make: Callable[..., Awaitable[AnyIterable[T]]]) -> None:
        self._make = make
        self._agen: AsyncIterator[T] | None = None

    def __await__(self) -> Generator[Any, None, AnyIterable[T]]:
        return self._make().__await__()

    def __aiter__(self) -> AsyncIterator[T]:
        return self

    async def __anext__(self) -> T:
        if self._agen is None:
            self._agen = as_async(await self._make())

        return await self._agen.__anext__()

    async def aclose(self) -> None:
        """Closes the parser's stream if consumption has started."""
        if is_async_closeable(self._agen):
            await self._agen.aclose()


class Module[B: (Literal[True], Literal[False])]:
    """
    Base for the ``processor``/``operator``/``splitter`` pipe decorators.

    Instantiated once per pipe at import time with the author's decoration
    options (``ftype``/``ptype``/``defaults``/…), then called to wrap the parser.
    Subclasses supply the ``parse``/``setup``/``process``/``__call__`` steps that
    turn a parser into a configured pipe; ``prepare`` builds the immutable
    per-call state those steps share.
    """

    isasync: B
    module_type: ClassVar[ModuleType]
    decoration_options: ClassVar[frozenset[str]]
    call_options: ClassVar[frozenset[str]] = _CALL_OPTS
    context_options: ClassVar[frozenset[str]] = _CONTEXT_OPTS
    call_record: ClassVar[type[_PreparedCall[Any]]]

    def __new__(cls, *args: object, **kwargs: object) -> object:
        """
        Creates the decorator, or wraps a function when applied bare.

        Applied without parentheses, the decorator wraps the function exactly as
        its called, option-free form does.

        Raises:

            TypeError: When the function to wrap is passed along with decoration
                options.

        """
        pipe = args[0] if args else None

        if callable(pipe) and (len(args) > 1 or kwargs):
            msg = f"@{cls.__name__} takes either the function to wrap or decoration "
            raise TypeError(msg + "options, not both")
        elif callable(pipe):
            wrap = cast("Callable[[Callable[..., object]], ModuleWrapper]", cls())
            result = wrap(pipe)
        else:
            result = super().__new__(cls)

        return result

    @overload
    def __init__(
        self: Module[Literal[True]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        pollable: bool = ...,
        ftype: BasicCastType = ...,
        ptype: BasicCastType = ...,
        **opts: object,
    ) -> None: ...
    @overload
    def __init__(
        self: Module[Literal[False]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        pollable: bool = ...,
        ftype: BasicCastType = ...,
        ptype: BasicCastType = ...,
        **opts: object,
    ) -> None: ...
    def __init__(
        self,
        defaults: Defaults | None = None,
        *,
        isasync: bool = False,
        pollable: bool = False,
        ftype: BasicCastType = BasicCastType.PASS,
        ptype: BasicCastType = BasicCastType.PASS,
        **opts: object,
    ):
        # Only called once on pipe import
        self.defaults: Defaults = defaults or Defaults()
        self._opts: DecorationOptions = DecorationOptions(ftype=ftype, ptype=ptype)
        self._opts.update(cast("DecorationOptions", opts))
        self.isasync = isasync  # pyright: ignore[reportAttributeAccessIssue]
        self.pollable: bool = pollable

    def _resolve_isasync(self, pipe: ModuleParser) -> bool:
        """
        Decides whether to build the async wrapper for a parser.

        ``isasync`` marks which interface this is (``pipe`` vs ``async_pipe``),
        not whether the function is async. I.e., a sync ``def async_pipe`` is
        valid. An async parser named ``pipe`` is a contradiction and raises.

        Args:

            pipe: The undecorated parser being wrapped.

        Returns:

            True when the async wrapper should be built.

        Raises:

            TypeError: When a parser named ``pipe`` is async or ``isasync=True``.

        """
        awaitable = is_async_callable(pipe)
        name = getattr(pipe, "__name__", "")
        isasync = self.isasync or awaitable or name == "async_pipe"

        if name == "pipe" and isasync:
            reason = "an async def" if awaitable else "marked isasync=True"
            qualified = f"{pipe.__module__}.{name}"
            raise TypeError(
                f"{qualified}: 'pipe' is the synchronous interface but is "
                f"{reason}; name the async interface 'async_pipe' instead."
            )

        return isasync

    def _set_wrapper_metadata(
        self, wrapper: ModuleWrapper, pipe: ModuleParser, isasync: bool
    ) -> None:
        """
        Stamps discovery metadata onto a finished wrapper.

        Derives and sets the module's name, subtype(s), and loopability from the parser
        and decoration options, and the ``prepare`` that prepares a call for reuse.

        Args:

            wrapper: The wrapper function to annotate.
            pipe: The undecorated parser it wraps.
            isasync: Whether the wrapper is the async interface.

        """
        module_type = self.module_type
        subtype, subtypes = get_module_subtypes(pipe, module_type, **self._opts)
        name = pipe.__module__.rsplit(".", 1)[-1]
        loopable = is_loopable(name, module_type)

        stamp_wrapper_meta(
            wrapper,
            name=name,
            module_type=module_type,
            subtype=subtype,
            subtypes=subtypes,
            pollable=self.pollable,
            loopable=loopable,
            isasync=isasync,
            sequential_inputs=has_sequential_inputs(name),
            prepare=partial(self.prepare_call, wrapper),
        )

    def _validate_call_keywords(
        self, wrapper: ModuleWrapper, names: Iterable[str]
    ) -> None:
        """
        Rejects decoration options handed to a module call.

        A decoration option (``skip_if``, ``ftype``, ``extract``, …) is fixed when the
        module is decorated. Passing one to a call or to ``prepare`` would otherwise be
        silently ignored, so it raises instead.

        Args:

            wrapper: The module wrapper being called.
            names: The keyword argument names the call supplied.

        Raises:

            TypeError: When any name is a decoration option this decorator reads.

        """
        fixed = self.decoration_options - self.call_options - self.context_options

        if invalid := sorted(fixed.intersection(names)):
            named = ", ".join(repr(key) for key in invalid)
            msg = f"the {wrapper.name!r} module fixes {named} when it is decorated, "
            msg += "not with each call"
            raise TypeError(msg)

    def prepare(
        self,
        module_name: str,
        *extras: ExtraName,
        conf: PrepareConf | None = None,
        **options: Unpack[RawCallOptions],
    ) -> PreparedModule[ItemOrValue, object]:
        """
        Builds immutable invocation state for a module call.

        Each call produces fresh state, so concurrent invocations and differing
        call options never overwrite one another.

        Args:

            module_name: The module name.

            extras: The names of the extra inputs delivered with each item: a
                named input stream under its port name, positional streams as
                ``others``, bound resources as ``resources``, and a loop's embed as
                ``embed``. A configuration value naming one is resolved per item.

        Kwargs:

            conf: The call-time configuration, merged over the module defaults.

            assign (str): The field results are assigned to. Defaults to the module
                name (or ``"content"`` for a source). Ignored when ``emit`` is true.

            emit (bool): Whether to emit results rather than assign them. Defaults to
                the parser's contract.

            field (str): The field whose value is passed to the pipe in place of the
                item.

            count (str): ``"first"`` stops after the first result. ``"all"`` keeps
                every result.

        Returns:

            The immutable ``PreparedModule`` for this call.

        """
        emit, assign = options.get("emit"), options.get("assign")
        def_emit = self._opts.get("emit") if emit is None else emit
        def_assign = self._opts.get("assign", "") if assign is None else assign
        opts: DecorationOptions = DecorationOptions(self._opts)
        opts.setdefault("objectify", self._opts.get("ptype") != BasicCastType.NONE)

        is_source = False

        if self.module_type == "operator":
            _emit = is_mapping if def_emit is None else def_emit
            _assign = def_assign or module_name
        else:
            is_source = self._opts.get("ftype") == BasicCastType.NONE
            _emit = (is_source or is_mapping) if def_emit is None else def_emit
            assignment = "content" if is_source else module_name
            _assign = def_assign or assignment

        module_conf = DotDict(self.defaults)
        module_conf.update(conf or {})
        _conf = require_conf(module_conf.asdict())

        if _emit and assign and not callable(_emit):
            msg = f"Assign is set to {assign} for {module_name} but will be "
            msg += "overridden since emit is True."
            logger.warning(msg)

        opts["emit"] = _emit
        opts["assign"] = _assign

        if "count" in options:
            opts["count"] = options["count"]

        return PreparedModule(
            name=module_name,
            conf=_conf,
            opts=opts,
            extras=extras,
            defaults=self.defaults,
        )

    def prepare_call(
        self,
        wrapper: ModuleWrapper,
        *extras: ExtraName,
        conf: PrepareConf | None = None,
        **options: Unpack[RawCallOptions],
    ) -> PreparedCall:
        """
        Prepares ``wrapper``'s configuration and call options for reuse over many items.

        Every module wrapper exposes this as its ``prepare``. The configuration and call
        options are resolved here. Each item call supplies the ``context`` and any
        secondary input streams, resources, or embed.

        Args:

            wrapper: The module wrapper this decorator built.

            extras: The names of the extra inputs delivered with each item: a named
                input stream under its port name, positional streams as ``others``,
                bound resources as ``resources``, and a loop's embed as ``embed``.

        Kwargs:

            conf: The module configuration.

            assign (str): The field results are assigned to. Defaults to the module
                name (or ``"content"`` for a source). Ignored when ``emit`` is true.

            emit (bool): Whether to emit results rather than assign them. Defaults to
                the parser's contract.

            field (str): The field whose value is passed to the pipe in place of the
                item.

            count (str): ``"first"`` stops after the first result. ``"all"`` keeps
                every result.

        Returns:

            A call that takes one item (or stream) at a time.

        Raises:

            TypeError: If ``options`` holds a keyword argument that is not a call
                option: a decoration option such as ``skip_if`` or ``ftype``, which is
                fixed when the module is decorated, or a per-item argument such as
                ``resources``, ``embed``, or a secondary input stream.

        Examples:

            >>> from riko.modules.strtransform import pipe
            >>>
            >>> conf = {"rule": {"transform": "upper"}}
            >>> call = pipe.prepare(conf=conf, field="x")
            >>> next(call({"x": "hi"}))
            {'x': 'hi', 'strtransform': 'HI'}
            >>> pipe.prepare("resources", resources={})
            Traceback (most recent call last):
                ...
            TypeError: the 'strtransform' module takes 'resources' with each item...
            >>> pipe.prepare(conf=conf, skip_if=lambda item: True)
            Traceback (most recent call last):
                ...
            TypeError: the 'strtransform' module fixes 'skip_if' when it is decorated...

        """
        self._validate_call_keywords(wrapper, options)

        if invalid := sorted(set(options).difference(self.call_options)):
            named = ", ".join(repr(key) for key in invalid)
            msg = f"the {wrapper.name!r} module takes {named} with each item call, "
            msg += "not as a call option"
            raise TypeError(msg)

        prepared = self.prepare(wrapper.name, *extras, conf=conf, **options)
        return self.call_record(self, wrapper, prepared, options)

    def _call_direct(
        self,
        wrapper: ModuleWrapper,
        items: object,
        *,
        conf: Conf | DynamicConf | None,
        context: Context | None,
        **kwargs: object,
    ) -> WrapperOutput | SplitterWrapperOutput:
        """
        Prepares a direct wrapper call and runs it once on ``items``.

        Every keyword name counts as a per-item input when preparing, because a direct
        call cannot differentiate an input port named like a call option (e.g., ``tail``
        uses ``count`` as an input stream).
        """
        self._validate_call_keywords(wrapper, kwargs)
        named = self.call_options | self.context_options
        call_options = {k: kwargs[k] for k in self.call_options.intersection(kwargs)}
        _overrides = {k: kwargs[k] for k in self.context_options.intersection(kwargs)}
        overrides = _require_overrides(_overrides)
        extra = {key: value for key, value in kwargs.items() if key not in named}
        options = _require_call_options(call_options)
        resolved = _resolve_context(context, **overrides) if overrides else context
        call = wrapper.prepare(*kwargs, conf=conf, **options)
        return call(items, context=resolved, **extra)


@overload
async def _materialize_terminal[T](value: AsyncIterable[T]) -> Iterator[T]: ...
@overload
async def _materialize_terminal[T](value: list[T] | tuple[T, ...]) -> list[T]: ...
@overload
async def _materialize_terminal[T](value: T) -> T: ...
async def _materialize_terminal[T](value: object) -> object:
    """
    Drains an async secondary input stream into a concrete sync iterator.

    A secondary input stream (an async pipeline passed as ``format``/``formatted`` or
    one of ``union``'s ``others``) reaches the synchronous conf-parsing machinery,
    which pulls it with ``next`` or ``chain``. An async iterable cannot satisfy this.

    Args:

        value: A call-time keyword value that may be an async stream, a list or tuple
            of streams, or an ordinary option.

    Returns:

        The value with any async stream drained to an iterator; other values are
        returned unchanged.

    """
    materialized: Iterator[T] | list[T] | T

    if isinstance(value, AsyncIterable):
        materialized = iter(await alist(value))
    elif is_known_sequence(value):
        materialized = [await _materialize_terminal(item) for item in value]
    else:
        materialized = cast("T", value)

    return materialized


async def _aprocess_stream[T](
    wrapper: Callable[[T], Awaitable[Iterable[ItemOrValue]]], stream: AsyncIterable[T]
) -> AsyncIterator[ItemOrValue]:
    """
    Maps a processor over an async stream lazily, in order, flattening its results.

    Args:

        wrapper: The per-item processor call, returning that item's results.
        stream: The async stream of items to process.

    Yields:

        Each result of every item, in stream order.

    """
    async with aclosing(async_map_ordered_stream(wrapper, stream)) as mapped:
        async for processed in mapped:
            for value in processed:
                yield value


async def _materialize_terminals(**kwargs: object) -> dict[str, object]:
    """
    Drains any async secondary input streams held in call-time keyword arguments.

    The async operator and processor wrappers forward secondary input streams through
    ``**kwargs`` into the synchronous conf-parsing machinery. Each async stream is
    materialized once here so parsing consumes it like its synchronous counterpart.

    Args:

        **kwargs: The passthrough keyword arguments, possibly holding async streams.

    Returns:

        A new mapping with every async secondary input stream drained.

    """
    return {key: await _materialize_terminal(value) for key, value in kwargs.items()}


def _validate_opts(
    module_type: str, supported: frozenset[str], kwargs: Mapping[str, object]
) -> None:
    """
    Rejects decoration options a decorator does not read.

    A decoration-time author mistake evaluated once at import: an option a given
    module type never reads (e.g. ``skip_if`` on an operator, the ``count``
    keyword argument on a processor, or a misspelled name) would otherwise be silently
    ignored, so it raises instead.

    Args:

        module_type: The decorator name used in the error message.
        supported: Options this decorator reads at decoration time.
        kwargs: The decoration keyword arguments to validate.

    Raises:

        TypeError: When any unsupported option is present.

    """
    if invalid := sorted(set(kwargs).difference(supported)):
        named = ", ".join(repr(opt) for opt in invalid)
        msg = f"{module_type} modules do not support the {named} option(s); "
        msg += f"supported options are {', '.join(sorted(supported))}"
        raise TypeError(msg)


class _ProcessorCall(NamedTuple):
    """The state a processor parser call and its result assignment share."""

    input_: DotDict[RikoValue]
    casted: Casted[ItemOrValue, object]
    kwargs: dict[str, object]
    stream_count: CountValues | None


@define(frozen=True, slots=True)
class _PreparedCall[M: Module[Any]](PreparedCall):
    """
    A module call prepared once, holding what every prepared call kind shares.

    Attributes:

        module: The decorator that built the wrapper.
        wrapper: The module wrapper being called.
        prepared: The module's prepared call-time state.
        options: The prepared call options.

    """

    module: M
    wrapper: ModuleWrapper
    prepared: PreparedModule[ItemOrValue, object]
    options: RawCallOptions

    @property
    def parser(self) -> Callable[..., Any]:
        """The undecorated parser the module wrapper wraps."""
        return vars(self.wrapper)["__wrapped__"]

    @property
    def field(self) -> str | None:
        """The item field whose value the parser receives, else ``None``."""
        return self.options.get("field")

    @property
    def count(self) -> CountValues | None:
        """Whether to keep the first result or all of them, else ``None``."""
        return self.options.get("count")


@define(frozen=True, slots=True)
class _PreparedProcessor(_PreparedCall["processor[Any]"]):
    """A processor call prepared once and run once per item."""

    def __call__(
        self,
        item: ProcessorWrapperInput | None = None,
        *,
        context: Context | None = None,
        **extra: object,
    ) -> SyncProcessorWrapperOutput | AsyncProcessorWrapperOutput:
        if self.wrapper.isasync:
            make = partial(self._arun, item, context, extra)
            result = cast("AsyncProcessorWrapperOutput", _AsyncWrapperStream(make))
        else:
            result = cast("SyncProcessorWrapperOutput", self._run(item, context, extra))

        return result

    def _start(
        self, item: ItemOrValue, context: Context | None, extra: dict[str, object]
    ) -> _ProcessorCall | StreamOrValueStream:
        """Prepares an item for its parser, or passes it through when skipped."""
        module, prepared = self.module, self.prepared
        count, field = self.count, self.field
        input_ = module.normalize_input(item)
        sargs = (prepared, input_, field)
        skwargs = {"count": count, **extra}
        orig_item, casted, skip = module.setup(*sargs, **skwargs)

        if skip:
            args = (input_, orig_item, prepared.assign)
            built = module.process(*args, emit=True, skip=True)
        else:
            resolved = _resolve_context(context)
            pkwargs = {"inputs": resolved.inputs, "count": count, **extra}
            pkwargs["test"] = resolved.test
            built = _ProcessorCall(input_, casted, pkwargs, count)

        return built

    def _finish[O: ItemOrValue](
        self, call: _ProcessorCall, stream: ProcessorParserOutput[O]
    ) -> StreamOrValueStream:
        """Assigns or emits a parser's result for a prepared item."""
        emit = self.prepared.resolve_emit(stream)
        args = (call.input_, stream, self.prepared.assign)
        return self.module.process(*args, emit=emit, count=call.stream_count)

    def _run(
        self,
        item: SyncProcessorWrapperInput | None,
        context: Context | None,
        extra: dict[str, object],
    ) -> SyncProcessorWrapperInternalOutput:
        if is_listlike(item):
            run = partial(self._run, context=context, extra=extra)
            processed = chain.from_iterable(map(run, item))
        else:
            call = self._start(cast("ItemOrValue", item), context, extra)

            if isinstance(call, _ProcessorCall):
                casted = call.casted
                args = (casted.field, casted.extraction, casted.conf)
                stream = self.parser(*args, **call.kwargs)
                processed = self._finish(call, stream)
            else:
                processed = call

        yield from processed

    async def _arun(
        self,
        item: ProcessorWrapperInput | None,
        context: Context | None,
        extra: dict[str, object],
    ) -> AsyncProcessorWrapperInternalOutput:
        extra = await _materialize_terminals(**extra)
        processed: AsyncProcessorWrapperInternalOutput

        if is_streamlike(item):
            _run = partial(self._arun, context=context, extra=extra)
            run = cast("AsyncItemProcessor", _run)

            if isinstance(item, AsyncIterable):
                processed = _aprocess_stream(run, item)
            else:
                mapped = await async_map(run, item)
                processed = chain.from_iterable(mapped)
        else:
            call = self._start(cast("ItemOrValue", item), context, extra)

            if isinstance(call, _ProcessorCall):
                casted = call.casted
                args = (casted.field, casted.extraction, casted.conf)
                parsed = self.parser(*args, **call.kwargs)
                stream = await as_awaitable(parsed)
                processed = self._finish(call, stream)
            else:
                processed = call

        return processed


@define(frozen=True, slots=True)
class _PreparedOperator(_PreparedCall["operator[Any]"]):
    """An operator call prepared once and run once per stream."""

    def __call__(
        self,
        item: AsyncOperatorWrapperInput | None = None,
        *,
        context: Context | None = None,
        **extra: object,
    ) -> SyncOperatorWrapperOutput | AsyncOperatorWrapperOutput:
        if self.wrapper.isasync:
            stream = self._agen(item, context, extra)
            result = cast("AsyncOperatorWrapperOutput", stream)
        else:
            items = cast("SyncOperatorWrapperInput", item)
            result = cast("SyncOperatorWrapperOutput", self._gen(items, context, extra))

        return result

    @property
    def embedded_kwargs(self) -> EmbedKwargs | None:
        """The conf and emit ``loop`` hands its embed, else ``None``."""
        prepared = self.prepared

        if prepared.name == "loop":
            embedded_kwargs = EmbedKwargs(conf=prepared.conf, emit=True)
        else:
            embedded_kwargs = None

        return embedded_kwargs

    def _finish[T: ItemOrValue](
        self, stream: OperatorParserOutput[T]
    ) -> StreamOrValueStream:
        """Assigns or emits a parser's result."""
        emit = self.prepared.resolve_emit(stream)
        return self.module.process(stream, self.prepared.assign, emit=emit)

    def _gen(
        self,
        items: SyncOperatorWrapperInput | None,
        context: Context | None,
        extra: dict[str, object],
    ) -> SyncOperatorWrapperInternalOutput:
        kwargs = dict(extra)
        _embed = kwargs.pop("embed", None)
        embed = cast("SyncProcessorWrapper | SyncSubPipe | None", _embed)
        prepared = self.prepared
        field, count = self.field, self.count
        input_ = self.module.normalize_input(items)
        resolved = _resolve_context(context)
        pkwargs = {"inputs": resolved.inputs, "count": count, **kwargs}
        args = (prepared, input_)
        tuples, orig_stream, casted = self.module.setup(*args, field=field, **pkwargs)
        handled, looped, embed_stream = loop_embed_sync(
            embed,
            self.embedded_kwargs,
            resolved,
            input_,
            prepared.name,
            field=field,
            assign=prepared.assign,
            emit=bool(prepared.emit),
            count=count,
        )

        if looped or handled:
            processed = embed_stream
        else:
            parser = self.parser
            sync_pipe = cast("SyncOperatorParser[ItemOrValue, object]", parser)
            stream = sync_pipe(orig_stream, casted.extraction, tuples, **pkwargs)
            processed = self._finish(stream)

        yield from processed

    async def _agen(
        self,
        items: AsyncOperatorWrapperInput | None,
        context: Context | None,
        extra: dict[str, object],
    ) -> AsyncOperatorWrapperInternalOutput:
        parser = self.parser
        async_native = is_async_callable(parser)

        if isinstance(items, AsyncIterable):
            # Async-native composers (async def async_pipe, e.g. timeout/send)
            # consume the async stream lazily to bound an infinite Feed. Legacy
            # aggregators reuse the sync parser, which can't iterate async
            # tuples, so materialize the async input here.
            if async_native:
                input_ = self.module.anormalize_input(items)
            else:
                _items = await alist(self.module.anormalize_input(items))
                input_ = iter(_items)
        else:
            input_ = self.module.normalize_input(items)

        kwargs = dict(extra)
        _embed = kwargs.pop("embed", None)
        embed = cast("AsyncProcessorWrapper | AsyncSubPipe | None", _embed)
        kwargs = await _materialize_terminals(**kwargs)
        prepared = self.prepared
        field, count = self.field, self.count
        resolved = _resolve_context(context)
        pkwargs = {"inputs": resolved.inputs, "count": count, **kwargs}
        args = (prepared, input_)
        tuples, orig_stream, casted = self.module.setup(*args, field=field, **pkwargs)
        handled, looped, embed_stream = loop_embed_async(
            embed,
            self.embedded_kwargs,
            resolved,
            input_,
            prepared.name,
            field=field,
            assign=prepared.assign,
            emit=bool(prepared.emit),
            count=count,
        )

        if looped or handled:
            processed = as_async(embed_stream)
        else:
            if async_native:
                args = (orig_stream, casted.extraction, tuples)
                stream = await parser(*args, **pkwargs)
            elif isinstance(orig_stream, Iterator) and isinstance(tuples, Iterator):
                stream = parser(orig_stream, casted.extraction, tuples, **pkwargs)
            else:
                msg = "Async parser must be async def to parse async iterators"
                raise TypeError(msg)

            processed = async_iter(self._finish(stream))

        async for item in processed:
            yield item


@define(frozen=True, slots=True)
class _PreparedSplitter(_PreparedCall["splitter[Any]"]):
    """A splitter call prepared once and run once per stream."""

    def __call__(
        self,
        item: SplitterWrapperInput | None = None,
        *,
        context: Context | None = None,
        **extra: object,
    ) -> SplitterWrapperOutput:
        kwargs = extra if context is None else {**extra, "context": context}

        if self.wrapper.isasync:
            stream = _AsyncWrapperStream(partial(self._arun, item, kwargs))
            result = cast("AsyncSplitterWrapperOutput", stream)
        else:
            result = self._run(item, kwargs)

        return result

    def _parse(
        self, items: SplitterWrapperInput | None, kwargs: dict[str, object]
    ) -> object:
        """Runs the parser over the prepared input stream."""
        field = self.field
        input_ = self.module.normalize_input(items)
        prepared = self.prepared
        args = (prepared, input_)
        tuples, orig_stream, casted = self.module.setup(*args, field=field, **kwargs)
        return self.parser(orig_stream, casted.extraction, tuples, **kwargs)

    def _run(
        self, items: SplitterWrapperInput | None, kwargs: dict[str, object]
    ) -> SyncSplitterWrapperOutput:
        yield from cast("SyncSplitterWrapperOutput", self._parse(items, kwargs))

    async def _arun(
        self, items: SplitterWrapperInput | None, kwargs: dict[str, object]
    ) -> SyncSplitterWrapperOutput:
        parsed = cast(
            "Awaitable[SyncSplitterWrapperOutput] | SyncSplitterWrapperOutput",
            self._parse(items, kwargs),
        )
        return await as_awaitable(parsed)


def _wrap_item(item: ItemOrValue) -> DotDict[RikoValue]:
    """Wraps a mapping as a ``DotDict`` and any other value under ``"content"``."""
    _item = item if is_mapping(item) else {"content": item}
    return DotDict(_item)


class processor[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    """Creates a pipe callable that processes individual items."""

    isasync: B
    module_type: ClassVar[ModuleType] = "processor"
    decoration_options: ClassVar[frozenset[str]] = _PROCESSOR_OPTS
    call_record: ClassVar[type[_PreparedCall[Any]]] = _PreparedProcessor

    @overload
    def __new__[I, E, O: ItemOrValue](
        cls, pipe: AwaitableProcessorParser[I, E, O], /
    ) -> AsyncProcessorWrapper: ...
    @overload
    def __new__[I, E, O: ItemOrValue](
        cls, pipe: SyncProcessorParser[I, E, O], /
    ) -> SyncProcessorWrapper: ...
    @overload
    def __new__(
        cls,
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> processor[Literal[True]]: ...
    @overload
    def __new__(
        cls,
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> processor[Literal[False]]: ...
    def __new__(cls, *args: object, **kwargs: object) -> Any:
        return super().__new__(cls, *args, **kwargs)

    @overload
    def __init__(
        self: processor[Literal[True]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> None: ...
    @overload
    def __init__(
        self: processor[Literal[False]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> None: ...
    def __init__(self, *args: object, **kwargs: object):
        """
        Configures a sync/async pipe that processes individual items.

        Modules built this way are ``type: processor`` and either
        ``subtype: transformer`` or ``subtype: source`` (a source sets ``ftype`` to
        ``"none"``).

        Keyword arguments such as ``conf`` and ``count`` go to the wrapped pipe, not the
        decorator.

        Args:

            defaults (dict): Default ``conf`` values (default: None).

        Kwargs:

            isasync (bool): Wraps an async pipe (default: False).

            pollable (bool): Marks the pipe as pollable for discovery (default: False).

            extract (str): Key whose ``conf`` value is passed to the pipe in place of
                ``conf`` (default: None).

            listize (bool): Ensure an ``extract`` value is list-like (default: False).

            objectify (bool): Convert ``conf`` to a ``meza.fntools.Objectify`` instance
                (default: True unless ``ptype`` is ``"none"``).

            ptype (str): Converts ``conf`` items to a type after objectifying. One of
                ``"pass"``, ``"none"``, ``"text"``, ``"int"``, ``"float"``, or
                ``"decimal"``; ``"none"`` disables ``objectify`` (default: "pass").

            field (str): Field whose value is passed to the pipe in place of ``item``
                (default: None).

            ftype (str): Converts the input ``item`` to a type after reading ``field``.
                Same choices as ``ptype``; ``"none"`` enables ``emit`` and marks the
                module a source (default: "pass").

            assign (str): Field the stream is assigned to (default: "content" for a
                source, module name otherwise). Ignored when ``emit`` is true.

            emit (bool): Return the stream as is instead of assigning it. Overrides
                ``assign`` (default: derived from ``ftype``).

            skip_if (callable): Callable taking the ``item`` that returns True to skip
                processing, leaving the original item unchanged (default: None).

        Raises:

            TypeError: When an option the processor does not read is passed, such as
                the operator-only ``embed`` or the ``count`` keyword argument.

        Examples:

            >>> from riko import async_return, issync, run
            >>>
            >>> @processor
            ... def pipe(item, extraction, objconf, **kwargs):
            ...     content = item["content"]
            ...     return f'say "{content}" {objconf.times} times!'
            >>>
            >>> @processor
            ... async def async_pipe(item, extraction, objconf, **kwargs):
            ...     content = await async_return(item["content"])
            ...     return f'say "{content}" {objconf.times} times!'
            >>>
            >>> item = {"content": "hello world"}
            >>> kwargs = {"conf": {"times": "three"}, "assign": "content"}
            >>> next(pipe(item, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>> async def main():
            ...     result = async_pipe(item, **kwargs)
            ...     print(await anext(result))
            >>>
            >>> if issync:
            ...     {"content": 'say "hello world" three times!'}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}

        """
        _validate_opts(self.module_type, self.decoration_options, kwargs)
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def normalize_input(self, item: ItemOrValue) -> DotDict[RikoValue]:
        """
        Normalizes a single input item into a ``DotDict``.

        ``None`` becomes an empty item (so source modules still fire), a mapping is
        wrapped directly, and any other value is placed under ``"content"``.

        Args:

            item: The raw input item or value.

        Returns:

            The item as a ``DotDict``.

        """
        if item is None:
            parsed: DotDict[RikoValue] = DotDict()
        else:
            parsed = _wrap_item(item)

        return parsed

    def setup[I, E](
        self,
        prepared: PreparedModule[I, E],
        input_: DotDict[RikoValue],
        field: str | None = None,
        **kwargs: object,
    ) -> tuple[ItemOrValue, Casted[I, E] | Casted[ItemOrValue, E], bool]:
        """
        Extracts and casts the input for a processor call.

        Uses the module's precomputed static cast when the conf does not vary per
        item, else parses and casts per call. Also resolves the per-item ``skip``.

        Args:

            prepared: The immutable per-call state from ``prepare``.
            input_: The parsed input item.
            field: Optional field whose value replaces the whole item.
            **kwargs: Extra keyword arguments forwarded to parsing.

        Returns:

            The original item, the cast field/extraction/conf, and the skip flag.

        """
        skip = get_skip(input_, skip_if=prepared.opts.get("skip_if"))

        if prepared.static_casted:
            field_func, pre_casted_extract, pre_casted_conf = prepared.static_casted
            field = prepared.opts.get("field", "") if field is None else field
            parsed_field = get_field(input_, field=field, **kwargs)
            casted_field = field_func(parsed_field)
            orig_item = input_
            casted = Casted(casted_field, pre_casted_extract, pre_casted_conf)
        else:
            args = (input_, prepared.opts)
            orig_item, casted = resolve_and_cast(
                *args,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=self.defaults,
                field=field,
                module=prepared.name,
                **kwargs,
            )

        return orig_item, casted, skip

    def process[O: ItemOrValue](
        self,
        input_: DotDict[RikoValue],
        stream: ProcessorParserOutput[O],
        assign: str,
        emit: bool = False,
        skip: bool = False,
        count: CountValues | None = None,
    ) -> StreamOrValueStream:
        """
        Assigns a parser's result back into the stream.

        On ``emit`` or ``skip`` the value passes straight through; otherwise the
        result is merged into the item under ``assign``.

        Args:

            input_: The original input item to merge into.
            stream: The parser's results.
            assign: The field the result is assigned to.
            emit: Whether to emit the result rather than assign it.
            skip: Whether the item was skipped (passed through unchanged).
            count: Optional stream-count reduction.

        Returns:

            The resulting stream.

        """
        if skip or emit:
            _, result = build_assignment(stream, skip=skip, count=count)
        else:
            one, assignment = build_assignment(stream, skip=False, count=count)
            result = gen_assignments(input_, assignment, assign=assign, one=one)

        return result

    @overload
    def __call__[I, E, O: ItemOrValue](
        self: processor[Literal[True]], pipe: AsyncProcessorParser[I, E, O]
    ) -> AsyncProcessorWrapper: ...
    @overload
    def __call__[I, E, O: ItemOrValue](
        self: processor[Literal[False]], pipe: AwaitableProcessorParser[I, E, O]
    ) -> AsyncProcessorWrapper: ...
    @overload
    def __call__[I, E, O: ItemOrValue](
        self: processor[Literal[False]], pipe: SyncProcessorParser[I, E, O]
    ) -> SyncProcessorWrapper: ...
    def __call__[I, E, O: ItemOrValue](
        self, pipe: ProcessorParser[I, E, O]
    ) -> ProcessorWrapper:
        """
        Creates a sync or async pipe that processes individual items.

        Args:

            pipe: Parser called with the extracted content and parsed config.

        Returns:

            A pipe callable that takes an item and pipe options.

        Examples:

            >>> from riko import run, issync
            >>>
            >>> opts = {
            ...     "ftype": "text", "extract": "times", "listize": True,
            ...     "emit": True, "field": "content", "objectify": False
            ... }
            >>> wrapper = processor(**opts)
            >>> item = {"content": "hello world"}
            >>> kwargs = {"conf": {"times": "three"}, "assign": "content"}
            >>>
            >>> def pipe(content, times, objconf, **kwargs):
            ...     return f'say "{content}" {times[0]} times!'
            >>>
            >>> wrapped_pipe = wrapper(pipe)
            >>> next(wrapped_pipe(item, **kwargs))
            'say "hello world" three times!'
            >>> async_wrapper = processor(isasync=True, **opts)
            >>>
            >>> def async_pipe(content, times, objconf, **kwargs):
            ...     return f'say "{content}" {times[0]} times!'
            >>>
            >>> wrapped_async_pipe = async_wrapper(async_pipe)
            >>>
            >>> async def main():
            ...     result = await wrapped_async_pipe(item, **kwargs)
            ...     print(next(result))
            >>>
            >>> if issync:
            ...     print('say "hello world" three times!')
            ... else:
            ...     run(main)
            say "hello world" three times!

        """

        def async_wrapper(
            item: AsyncProcessorWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            **kwargs: object,
        ) -> AsyncProcessorWrapperOutput:
            args = (wrapper, item)
            output = self._call_direct(*args, conf=conf, context=context, **kwargs)
            return cast("AsyncProcessorWrapperOutput", output)

        def sync_wrapper(
            item: SyncProcessorWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            **kwargs: object,
        ) -> SyncProcessorWrapperInternalOutput:
            args = (wrapper, item)
            output = self._call_direct(*args, conf=conf, context=context, **kwargs)
            yield from cast("SyncProcessorWrapperInternalOutput", output)

        isasync = self._resolve_isasync(pipe)
        _wrapper = wraps(pipe)(async_wrapper if isasync else sync_wrapper)
        wrapper = cast("ProcessorWrapper", _wrapper)
        self._set_wrapper_metadata(wrapper, pipe, isasync)
        return wrapper


class operator[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    """Creates a pipe callable that processes an entire stream."""

    isasync: B
    module_type: ClassVar[ModuleType] = "operator"
    decoration_options: ClassVar[frozenset[str]] = _OPERATOR_OPTS
    call_record: ClassVar[type[_PreparedCall[Any]]] = _PreparedOperator

    @overload
    def __new__[T: ItemOrValue, E](
        cls, pipe: AwaitableOperatorParser[T, E], /
    ) -> AsyncOperatorWrapper: ...
    @overload
    def __new__[T: ItemOrValue, E](
        cls, pipe: SyncOperatorParser[T, E], /
    ) -> SyncOperatorWrapper: ...
    @overload
    def __new__(
        cls,
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> operator[Literal[True]]: ...
    @overload
    def __new__(
        cls,
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> operator[Literal[False]]: ...
    def __new__(cls, *args: object, **kwargs: object) -> Any:
        return super().__new__(cls, *args, **kwargs)

    @overload
    def __init__(
        self: operator[Literal[True]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> None: ...
    @overload
    def __init__(
        self: operator[Literal[False]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> None: ...
    def __init__(self, *args: object, **kwargs: object):
        """
        Configures a sync/async pipe that processes an entire stream.

        Keyword arguments such as ``conf``, ``count``, and ``embed`` go to the wrapped
        pipe, not the decorator.

        Args:

            defaults (dict): Default ``conf`` values (default: None).

        Kwargs:

            isasync (bool): Wraps an async pipe (default: False).

            pollable (bool): Marks the pipe as pollable for discovery (default: False).

            extract (str): Key whose ``conf`` values are passed to the pipe in place of
                ``conf`` (default: None).

            listize (bool): Ensure an ``extract`` value is list-like (default: False).

            objectify (bool): Convert ``conf`` to a ``meza.fntools.Objectify`` instance
                (default: True unless ``ptype`` is ``"none"``).

            ptype (str): Converts ``conf`` items to a type after objectifying. One of
                ``"pass"``, ``"none"``, ``"text"``, ``"int"``, ``"float"``, or
                ``"decimal"``; ``"none"`` disables ``objectify`` (default: "pass").

            field (str): Field whose values are passed to the pipe in place of ``items``
                (default: None).

            ftype (str): Converts the input ``items`` to a type after reading ``field``.
                Same choices as ``ptype`` (default: "pass").

            assign (str): Field the stream is assigned to (default: the module name).
                Ignored when ``emit`` is true.

            emit (bool): Return the stream as is instead of assigning it. Overrides
                ``assign`` (default: derived from ``ftype``).

        Raises:

            TypeError: When an option the operator does not read is passed, such as the
                processor-only ``skip_if`` or the ``embed`` keyword argument.

        Examples:

            >>> from riko import async_return, issync, run
            >>>
            >>> @operator(emit=False)
            ... def pipe1(stream, objconf, tuples, **kwargs):
            ...     for item, objconf in tuples:
            ...         s = 'say "{content}" {0} times!'
            ...         yield s.format(objconf.times, **item)
            >>>
            >>> @operator(emit=False)
            ... def pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item["content"].split()) for item in stream)
            >>>
            >>> @operator(emit=False)
            ... async def async_pipe1(stream, objconf, tuples, **kwargs):
            ...     item, objconf = next(tuples)
            ...     content = await async_return(item["content"])
            ...     return f'say "{content}" {objconf.times} times!'
            >>>
            >>> # Explicit isasync=True needed since async_pipe2 is not named async_pipe
            >>> # and it is not an async function
            >>> @operator(isasync=True, emit=False)
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item["content"].split()) for item in stream)
            >>>
            >>> items = [{"content": "hello world"}, {"content": "bye world"}]
            >>> conf = {"times": "three"}
            >>> kwargs = {"conf": conf, "assign": "content", "emit": False}
            >>> next(pipe1(items, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>> next(pipe2(items, **kwargs))
            {'content': 4}
            >>>
            >>> async def main():
            ...     r1 = async_pipe1(items, **kwargs)
            ...     print(await anext(r1))
            ...     r2 = async_pipe2(items, **kwargs)
            ...     print(await anext(r2))
            >>>
            >>> if issync:
            ...     {"content": 'say "hello world" three times!'}
            ...     {"content": 4}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        _validate_opts(self.module_type, self.decoration_options, kwargs)
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def normalize_input(self, items: SyncOperatorWrapperInput | None = None) -> Stream:
        """
        Normalizes a sync input stream into ``DotDict`` items.

        Non-mapping elements are placed under ``"content"``; an empty or ``None``
        input yields nothing.

        Args:

            items: The input items, if any.

        Yields:

            Each input element as a ``DotDict``.

        """
        for item in items or []:
            yield _wrap_item(item)

    async def anormalize_input(self, items: AsyncItemsOrValues) -> AsyncStream:
        """
        Normalizes an async input stream into ``DotDict`` items.

        The async counterpart of ``normalize_input``; a lazy pass-through that never
        drains the input stream, so composer operators can bound an infinite ``Feed``.

        Args:

            items: The async input items.

        Yields:

            Each input element as a ``DotDict``.

        """
        async for item in items:
            yield _wrap_item(item)

    @overload
    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: Stream,
        field: str | None = ...,
        **kwargs: object,
    ) -> tuple[SyncPipeTuples, Stream, Casted[Item, E] | Casted[T, E]]: ...
    @overload
    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: AsyncStream,
        field: str | None = ...,
        **kwargs: object,
    ) -> tuple[AsyncPipeTuples, AsyncStream, Casted[Item, E] | Casted[T, E]]: ...
    @overload
    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: Stream | AsyncStream,
        field: str | None = ...,
        **kwargs: object,
    ) -> tuple[PipeTuples, Stream | AsyncStream, Casted[Item, E] | Casted[T, E]]: ...
    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: Stream | AsyncStream,
        field: str | None = None,
        **kwargs: object,
    ) -> tuple[PipeTuples, Stream | AsyncStream, Casted[Item, E] | Casted[T, E]]:
        """
        Builds the per-item tuples and original stream for an operator call.

        The two returned iterators are lazy views over one shared input: a parser reads
        whichever it needs, never both. ``tuples`` pairs each item with its own config
        (``(item, objconf)``) and serves a parser that reads config per item;
        ``orig_stream`` is just the items and serves a parser that applies one config
        to the whole stream (it may also carry secondary input streams). The
        precomputed static cast is reused when the config does not vary per item.

        Args:

            prepared: The immutable per-call state from ``prepare``.
            input_: The parsed sync or async input stream.
            field: Optional field whose value replaces each item.
            **kwargs: Extra keyword arguments forwarded to parsing.

        Returns:

            The per-item tuples, the original stream, and the cast extraction/conf.

        """
        if prepared.static_casted:
            _, pre_casted_extract, pre_casted_conf = prepared.static_casted
            objconf = pre_casted_conf
            casted = Casted[Item, E](DotDict(), pre_casted_extract, pre_casted_conf)
            orig_stream = input_

            if isinstance(input_, AsyncIterator):
                tuples = ((item, objconf) async for item in input_)
            else:
                tuples = ((item, objconf) for item in input_)
        else:
            _disp = partial(
                resolve_and_cast,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=self.defaults,
                field=field,
                module=prepared.name,
            )
            # Parses conf that can vary per item. Can't handle secondary input streams
            dispatcher = cast("ItemDispatcher[T, E]", _disp)

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and full objconf
            # - orig_stream parses conf that doesn't vary per item; may hold input
            if isinstance(input_, AsyncIterator):
                adispatches = (dispatcher(item, prepared.opts) async for item in input_)
                tuples = ((d.item, d.casted.conf) async for d in adispatches)
                orig_stream = (d.item async for d in adispatches)
            else:
                dispatches = (dispatcher(item, prepared.opts) for item in input_)
                tuples = ((d.item, d.casted.conf) for d in dispatches)
                orig_stream = (d.item for d in dispatches)

            casted = dispatcher(DotDict(), prepared.opts, **kwargs).casted

        return (tuples, orig_stream, casted)

    def process[T: ItemOrValue](
        self, stream: OperatorParserOutput[T], assign: str, emit: bool = False
    ) -> StreamOrValueStream:
        """
        Assigns an operator parser's result into a single-item stream.

        Operators nest: on ``emit`` the value passes through, otherwise it is
        assigned under ``assign`` into a fresh empty item (never merged).

        Args:

            stream: The parser's results.
            assign: The field the result is assigned to.
            emit: Whether to emit the result rather than assign it.

        Returns:

            The resulting stream.

        """
        items = stream
        one, assignment = build_assignment(items, skip=False)

        if emit:
            result = assignment
        else:
            result = gen_assignments(DotDict(), assignment, assign=assign, one=one)

        return result

    @overload
    def __call__[T: ItemOrValue, E](
        self: operator[Literal[True]], pipe: AsyncOperatorParser[T, E]
    ) -> AsyncOperatorWrapper: ...
    @overload
    def __call__[T: ItemOrValue, E](
        self: operator[Literal[False]], pipe: AwaitableOperatorParser[T, E]
    ) -> AsyncOperatorWrapper: ...
    @overload
    def __call__[T: ItemOrValue, E](
        self: operator[Literal[False]], pipe: SyncOperatorParser[T, E]
    ) -> SyncOperatorWrapper: ...
    def __call__[T: ItemOrValue, E](
        self, pipe: OperatorParser[T, E]
    ) -> OperatorWrapper:
        """
        Creates a sync or async pipe that processes an entire stream.

        Args:

            pipe: Parser called with the stream, parsed config, and tuples.

        Returns:

            A pipe callable that takes a stream and pipe options.

        Examples:

            >>> from riko import run, issync
            >>>
            >>> opts = {
            ...     "ftype": "text", "extract": "times", "listize": True,
            ...     "field": "content", "objectify": False
            ... }
            >>> wrapper = operator(**opts)
            >>> items = [{"content": "hello world"}, {"content": "bye world"}]
            >>> conf = {"times": "three"}
            >>> kwargs = {"conf": conf, "assign": "content", "emit": False}
            >>>
            >>> def pipe1(stream, times, tuples, **kwargs):
            ...     for content, objconf in tuples:
            ...         yield 'say "{content}" {0} times!'.format(*times, **content)
            >>>
            >>> wrapped_pipe1 = wrapper(pipe1)
            >>> next(wrapped_pipe1(items, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>>
            >>> def pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item["content"].split()) for item in stream)
            >>>
            >>> wrapped_pipe2 = wrapper(pipe2)
            >>> next(wrapped_pipe2(items, **kwargs))
            {'content': 4}
            >>> async_wrapper = operator(isasync=True, **opts)
            >>>
            >>> def async_pipe1(stream, times, tuples, **kwargs):
            ...     for content, objconf in tuples:
            ...         yield 'say "{content}" {0} times!'.format(*times, **content)
            >>>
            >>> async def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     return sum(len(item["content"].split()) for item in stream)
            >>>
            >>> wrapped_async_pipe1 = async_wrapper(async_pipe1)
            >>> wrapped_async_pipe2 = async_wrapper(async_pipe2)
            >>>
            >>> async def main():
            ...     r1 = wrapped_async_pipe1(items, **kwargs)
            ...     print(await anext(r1))
            ...     r2 = wrapped_async_pipe2(items, **kwargs)
            ...     print(await anext(r2))
            >>>
            >>> if issync:
            ...     {"content": 'say "hello world" three times!'}
            ...     {"content": 4}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """

        async def async_wrapper(
            items: AsyncOperatorWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            **kwargs: object,
        ) -> AsyncOperatorWrapperInternalOutput:
            args = (wrapper, items)
            output = self._call_direct(*args, conf=conf, context=context, **kwargs)
            stream = cast("AsyncOperatorWrapperInternalOutput", output)

            async for item in stream:
                yield item

        def sync_wrapper(
            items: SyncOperatorWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            **kwargs: object,
        ) -> SyncOperatorWrapperInternalOutput:
            args = (wrapper, items)
            output = self._call_direct(*args, conf=conf, context=context, **kwargs)
            yield from cast("SyncOperatorWrapperInternalOutput", output)

        isasync = self._resolve_isasync(pipe)
        _wrapper = wraps(pipe)(async_wrapper if isasync else sync_wrapper)
        wrapper = cast("OperatorWrapper", _wrapper)
        self._set_wrapper_metadata(wrapper, pipe, isasync)
        return wrapper


class splitter[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    """Creates a pipe callable that splits a stream into multiple streams."""

    isasync: B
    module_type: ClassVar[ModuleType] = "splitter"
    decoration_options: ClassVar[frozenset[str]] = _SPLITTER_OPTS
    call_options: ClassVar[frozenset[str]] = _SPLITTER_CALL_OPTS
    context_options: ClassVar[frozenset[str]] = frozenset()
    call_record: ClassVar[type[_PreparedCall[Any]]] = _PreparedSplitter

    @overload
    def __new__[E](
        cls, pipe: AwaitableSplitterParser[E], /
    ) -> AsyncSplitterWrapper: ...
    @overload
    def __new__[E](cls, pipe: SyncSplitterParser[E], /) -> SyncSplitterWrapper: ...
    @overload
    def __new__(
        cls,
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> splitter[Literal[True]]: ...
    @overload
    def __new__(
        cls,
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> splitter[Literal[False]]: ...
    def __new__(cls, *args: object, **kwargs: object) -> Any:
        return super().__new__(cls, *args, **kwargs)

    @overload
    def __init__(
        self: splitter[Literal[True]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> None: ...
    @overload
    def __init__(
        self: splitter[Literal[False]],
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> None: ...
    def __init__(self, *args: object, **kwargs: object):
        """
        Configures a sync/async pipe that splits a stream into copies.

        Keyword arguments such as ``conf`` go to the wrapped pipe, not the decorator.

        Args:

            defaults (dict): Default ``conf`` values (default: None).

        Kwargs:

            isasync (bool): Wraps an async pipe (default: False).

            extract (str): Key whose ``conf`` value is passed to the pipe in place of
                ``conf`` (default: None).

            listize (bool): Ensure an ``extract`` value is list-like (default: False).

            objectify (bool): Convert ``conf`` to a ``meza.fntools.Objectify`` instance
                (default: True unless ``ptype`` is ``"none"``).

            ptype (str): Converts ``conf`` items to a type after objectifying (default:
                "pass").

            field (str): Field whose value is passed to the pipe in place of ``items``
                (default: None).

            ftype (str): Converts the input ``items`` to a type after reading ``field``
                (default: "pass").

            assign (str): Field the streams are assigned to (default: the module name).

        Raises:

            TypeError: When an option the splitter does not read is passed, such as the
                processor/operator-only ``pollable``, ``emit``, or ``skip_if``, or the
                ``count`` or ``embed`` keyword argument.

        Examples:

            >>> @splitter(objectify=False)
            ... def pipe(stream, objconf, tuples, **kwargs):
            ...     items = list(stream)
            ...     return iter([iter(items), iter(items)])
            >>>
            >>> s1, s2 = pipe([{"x": 1}, {"x": 2}])
            >>> next(s1)
            {'x': 1}

        """
        _validate_opts(self.module_type, self.decoration_options, kwargs)
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def normalize_input(self, items: SplitterWrapperInput | None = None) -> Stream:
        """
        Normalizes an input stream into ``DotDict`` items.

        Non-mapping elements are placed under ``"content"``; an empty or ``None``
        input yields nothing.

        Args:

            items: The input items, if any.

        Yields:

            Each input element as a ``DotDict``.

        """
        if items:
            for item in items:
                data = item if is_mapping(item) else {"content": item}
                yield DotDict(data)

    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: Stream | SplitterWrapperInput,
        field: str | None = None,
        **kwargs: object,
    ) -> tuple[SyncPipeTuples, Stream, Casted[T, E]]:
        """
        Builds the per-item tuples and original stream for a splitter call.

        The two returned iterators are lazy views over one shared input: a parser reads
        whichever it needs, never both. ``tuples`` pairs each item with its own config
        (``(item, objconf)``) and serves a parser that reads config per item;
        ``orig_stream`` is just the items and serves a parser that applies one config
        to the whole stream.

        Args:

            prepared: The immutable per-call state from ``prepare``.
            input_: The input stream.
            field: Optional field whose value replaces each item.
            **kwargs: Extra keyword arguments forwarded to parsing.

        Returns:

            The per-item tuples, the original stream, and the cast extraction/conf.

        """
        _dispatcher = partial(
            resolve_and_cast,
            parsers=prepared.parsers,
            casters=prepared.casters,
            defaults=self.defaults,
            field=field,
        )
        dispatcher = cast("ItemDispatcher[T, E]", _dispatcher)
        dispatches = (dispatcher(item, prepared.opts) for item in input_)
        tuples = ((d.item, d.casted.conf) for d in dispatches)
        orig_stream = (d.item for d in dispatches)
        casted = dispatcher(DotDict(), prepared.opts, **kwargs).casted
        return (tuples, orig_stream, casted)

    @overload
    def __call__[E](
        self: splitter[Literal[True]], pipe: AsyncSplitterParser[E]
    ) -> AsyncSplitterWrapper: ...
    @overload
    def __call__[E](
        self: splitter[Literal[False]], pipe: AwaitableSplitterParser[E]
    ) -> AsyncSplitterWrapper: ...
    @overload
    def __call__[E](
        self: splitter[Literal[False]], pipe: SyncSplitterParser[E]
    ) -> SyncSplitterWrapper: ...
    def __call__[E](self, pipe: SplitterParser[E]) -> SplitterWrapper:
        """
        Creates a sync or async pipe that splits a stream into copies.

        Args:

            pipe: Parser called with the stream, parsed config, and tuples;
                returns an iterable of streams.

        Returns:

            A pipe callable that takes a stream and returns multiple streams.

        Examples:

            >>> wrapper = splitter(objectify=False)
            >>>
            >>> def pipe(stream, objconf, tuples, **kwargs):
            ...     items = list(stream)
            ...     return iter([iter(items), iter(items)])
            >>>
            >>> wrapped_pipe = wrapper(pipe)
            >>> s1, s2 = wrapped_pipe([{"x": 1}, {"x": 2}])
            >>> next(s1)
            {'x': 1}

        """

        def async_wrapper(
            items: AsyncSplitterWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            **kwargs: object,
        ) -> AsyncSplitterWrapperOutput:
            args = (wrapper, items)
            output = self._call_direct(*args, conf=conf, context=context, **kwargs)
            return cast("AsyncSplitterWrapperOutput", output)

        def sync_wrapper(
            items: SyncSplitterWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            **kwargs: object,
        ) -> SyncSplitterWrapperOutput:
            args = (wrapper, items)
            output = self._call_direct(*args, conf=conf, context=context, **kwargs)
            yield from cast("SyncSplitterWrapperOutput", output)

        isasync = self._resolve_isasync(pipe)
        _wrapper = wraps(pipe)(async_wrapper if isasync else sync_wrapper)
        wrapper = cast("SplitterWrapper", _wrapper)
        self._set_wrapper_metadata(wrapper, pipe, isasync)
        return wrapper
