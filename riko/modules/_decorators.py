# vim: sw=4:ts=4:expandtab
"""
riko.modules._decorators
~~~~~~~~~~~~~~~~~~~~~~~~~

Provides decorators for creating processor, operator, and splitter pipes.

Examples:
    Basic usage::

        >>> from riko.modules import processor
        >>>
        >>> @processor(isasync=False)
        ... def pipe(content, objconf, skip=False, **kwargs):
        ...     return content * objconf.times
        >>>
        >>> list(pipe({"x": 3}, conf={"times": 2}, field="x", assign="doubled"))
        [{'x': 3, 'doubled': 6}]

"""

from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterator, Mapping
from functools import partial, wraps
from inspect import isawaitable, iscoroutinefunction
from itertools import chain
from logging import Logger
from typing import ClassVar, Literal, cast, overload

import pygogo as gogo

from riko._iterutils import dispatch, is_listlike
from riko.bado.itertools import async_map
from riko.cast import BasicCastType
from riko.context import Context, ExecutionMode, parse_context
from riko.dotdict import DotDict, is_mapping
from riko.modules._assignment import gen_assignments, get_assignment
from riko.modules._derive import derive_loopable, derive_subtypes
from riko.modules._loop import loop_embed_async, loop_embed_sync
from riko.modules._prepare import (
    PreparedModule,
    get_casters,
    get_parsers,
    get_pieces_or_conf,
    parse_and_cast,
)
from riko.parsers import get_field, get_skip
from riko.resources import bind_resources, coerce_binding
from riko.types._collections import Inputs, RikoValue
from riko.types._dynamic_conf import DynamicConf
from riko.types._options import Casted, Defaults, ItemDispatch, Opts
from riko.types._scalars import PrimitiveValue
from riko.types._streams import (
    AsyncItemsOrValues,
    AsyncStream,
    Feed,
    Item,
    ItemOrValue,
    StatefulItem,
    Stream,
    StreamOrValueStream,
    Streams,
    ValueStream,
)
from riko.types._wrappers import (
    AsyncOperatorParser,
    AsyncOperatorWrapper,
    AsyncProcessorParser,
    AsyncProcessorWrapper,
    AsyncSplitterParser,
    AsyncSplitterWrapper,
    AsyncSubPipe,
    AwaitableOperatorParser,
    AwaitableProcessorParser,
    AwaitableSplitterParser,
    CastFuncs,
    ModuleParser,
    OperatorParser,
    OperatorParserOutput,
    OperatorWrapper,
    OperatorWrapperInput,
    OperatorWrapperOutput,
    PipeTuples,
    ProcessorParser,
    ProcessorParserOutput,
    ProcessorWrapper,
    ProcessorWrapperInput,
    ProcessorWrapperOutput,
    SplitterParser,
    SplitterWrapper,
    SplitterWrapperInput,
    SyncOperatorParser,
    SyncOperatorWrapper,
    SyncProcessorParser,
    SyncProcessorWrapper,
    SyncSplitterParser,
    SyncSplitterWrapper,
    SyncSubPipe,
)
from riko.types.compile import EmbedKwargs
from riko.types.modules import Conf, CountValues, ModuleType

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


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

    @overload
    def __init__(  # noqa: E704
        self: "Module[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        pollable: bool = ...,
        ftype: BasicCastType = ...,
        ptype: BasicCastType = ...,
        **opts: object,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "Module[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        pollable: bool = ...,
        ftype: BasicCastType = ...,
        ptype: BasicCastType = ...,
        **opts: object,
    ) -> None: ...
    def __init__(  # noqa: E301
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
        self._opts: Opts = Opts(ftype=ftype, ptype=ptype)
        self._opts.update(cast(Opts, opts))
        self.isasync = isasync  # pyright: ignore[reportAttributeAccessIssue]
        self.pollable: bool = pollable
        self.types: set[str] = set()

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
        awaitable = iscoroutinefunction(pipe)
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
        self, wrapper: wraps, pipe: ModuleParser, isasync: bool
    ) -> None:
        """
        Stamps discovery metadata onto a finished wrapper.

        Derives and sets the module's name, subtype(s), and loopability from the parser
        and decoration options.

        Args:
            wrapper: The wrapper function to annotate.
            pipe: The undecorated parser it wraps.
            isasync: Whether the wrapper is the async interface.

        Raises:
            TypeError: When the class name is not a known module type.

        """
        module_type = self.module_type

        if module_type not in {"operator", "processor", "splitter"}:
            raise TypeError(f"Unsupported module type: {module_type!r}")

        subtype, subtypes = derive_subtypes(pipe, module_type, **self._opts)
        name = pipe.__module__.rsplit(".", 1)[-1]
        loopable = derive_loopable(name, module_type)

        setattr(wrapper, "name", name)  # noqa: B010
        setattr(wrapper, "type", module_type)  # noqa: B010
        setattr(wrapper, "subtype", subtype)  # noqa: B010
        setattr(wrapper, "subtypes", subtypes)  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
        setattr(wrapper, "isasync", isasync)  # noqa: B010
        setattr(wrapper, "loopable", loopable)  # noqa: B010

    def prepare(
        self,
        module_name: str,
        conf: Conf | DynamicConf | None = None,
        *,
        assign: str | None = "",
        emit: bool | None = None,
        **kwargs: object,
    ) -> PreparedModule[ItemOrValue, object]:
        """
        Builds immutable invocation state for a module call.

        Each call produces fresh state, so concurrent invocations and differing
        call-site options never overwrite one another.

        Args:
            module_name: The pipe's module name.

            conf: The call-time configuration, merged over the module defaults.

            assign: The field results are assigned to; defaults to the pipe name
                (or ``"content"`` for a source). Ignored when ``emit`` is true.

            emit: Whether to emit results rather than assign them; defaults from
                the parser's contract.

            **kwargs: Extra call-time options folded into the resolved opts.

        Returns:
            The immutable ``PreparedModule`` for this call.

        """
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
            _emit = (is_source or is_mapping) if def_emit is None else def_emit
            assignment = "content" if is_source else module_name
            _assign = def_assign or assignment
        else:
            logger.error(f"Unknown module {self}.")
            _emit = def_emit
            _assign = def_assign

        module_conf = DotDict(self.defaults)
        module_conf.update(conf or {})
        _conf = cast(Conf, module_conf.asdict())

        if _emit and assign and not callable(_emit):
            msg = f"Assign is set to {assign} for {module_name} but will be "
            msg += "overridden since emit is True."
            logger.warning(msg)

        opts["emit"] = _emit
        opts["assign"] = _assign
        opts.update(cast(Opts, kwargs))

        parsers, is_dynamic = get_parsers(opts, conf=_conf, **kwargs)
        static_casted = None

        casters: CastFuncs[ItemOrValue, object] = get_casters(opts)

        if casters and not is_dynamic:
            parsed_conf = parsers.conf_parser({})
            args = (parsed_conf, self.defaults, opts, module_name)
            parsed = get_pieces_or_conf(*args)
            casted = dispatch(parsed, casters[1], casters[2])
            static_casted = (casters[0], casted[0], cast(DynamicConf, casted[1]))

        return PreparedModule(
            name=module_name,
            conf=_conf,
            opts=opts,
            parsers=parsers,
            casters=casters,
            assign=_assign,
            emit=_emit,
            is_source=is_source,
            static_casted=static_casted,
            resources=coerce_binding(opts.get("resources")),
        )


def _call_kwargs(
    prepared: PreparedModule[ItemOrValue, object],
    context: Context,
    count: CountValues | None,
    kwargs: Mapping[str, object],
) -> dict[str, object]:
    """
    Builds the keyword arguments passed to a parser call.

    Merges the run ``inputs``/``count`` and passthrough ``kwargs`` with the node's
    resolved ``resources`` view when it declares a binding.

    Args:
        prepared: The immutable per-call state, holding the resource binding.
        context: The parsed execution context.
        count: The stream count option.
        kwargs: The remaining passthrough options.

    Returns:
        The parser call kwargs, including ``resources`` when the node is bound.

    """
    pkwargs: dict[str, object] = {"inputs": context.inputs, "count": count, **kwargs}

    if prepared.resources is not None:
        pkwargs["resources"] = bind_resources(prepared.resources, context.resources)

    return pkwargs


_PROCESSOR_FORBIDDEN_OPTS: frozenset[str] = frozenset({"embed"})
_OPERATOR_FORBIDDEN_OPTS: frozenset[str] = frozenset({"skip_if"})
_SPLITTER_FORBIDDEN_OPTS: frozenset[str] = frozenset(
    {"pollable", "emit", "count", "skip_if", "embed"}
)


def _reject_foreign_opts(
    module_type: str, forbidden: frozenset[str], kwargs: Mapping[str, object]
) -> None:
    """
    Rejects decoration options that belong to a different decorator.

    A decoration-time author mistake evaluated once at import: an option a given
    pipe kind never reads (e.g. ``skip_if`` on an operator, ``embed`` on a
    processor) is a contradiction, so it raises rather than being silently
    ignored.

    Args:
        module_type: The decorator name used in the error message.
        forbidden: Options this decorator does not support.
        kwargs: The decoration keyword arguments to validate.

    Raises:
        TypeError: When any forbidden option is present.

    """
    invalid = sorted(forbidden.intersection(kwargs))

    if invalid:
        named = ", ".join(repr(opt) for opt in invalid)
        raise TypeError(f"{module_type} pipes do not support the {named} option(s)")


class processor[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    """Creates a pipe that processes individual items."""

    isasync: B
    module_type: ClassVar[ModuleType] = "processor"

    @overload
    def __init__(  # noqa: E704
        self: "processor[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "processor[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> None: ...
    def __init__(self, *args: object, **kwargs: object):  # noqa: E301
        """
        Configures a sync/async pipe that processes individual items.

        These pipes are ``type: processor`` and either ``subtype: transformer``
        or ``subtype: source`` (a source sets ``ftype`` to ``"none"``).

        Args:
            defaults (dict): Default ``conf`` values (default: None).

        Kwargs:
            isasync (bool): Wraps an async pipe (default: False).
            pollable (bool): Marks the pipe as pollable for discovery (default: False).
            conf (dict): The pipe configuration (default: None).

            extract (str): Key whose ``conf`` value is passed to the pipe in
                place of ``conf`` (default: None).

            listize (bool): Ensure an ``extract`` value is list-like (default:
                False).

            objectify (bool): Convert ``conf`` to a ``meza.fntools.Objectify``
                instance (default: True unless ``ptype`` is ``"none"``).

            ptype (str): Converts ``conf`` items to a type after objectifying.
                One of ``"pass"``, ``"none"``, ``"text"``, ``"int"``,
                ``"float"``, or ``"decimal"``; ``"none"`` disables ``objectify``
                (default: "pass").

            field (str): Key whose ``item`` value is passed to the pipe in place
                of ``item`` (default: None).

            ftype (str): Converts the input ``item`` to a type after reading
                ``field``. Same choices as ``ptype``; ``"none"`` enables
                ``emit`` and marks the pipe a source (default: "pass").

            count (str): Stream count, ``"first"`` (first result only) or
                ``"all"`` (all results in a list) (default: None).

            assign (str): Field the stream is assigned to (default: ``"content"``
                for a source, pipe name otherwise). Ignored when ``emit`` is
                true.

            emit (bool): Return the stream as is instead of assigning it.
                Overrides ``assign`` (default: derived from ``ftype``).

            skip_if (callable): Callable taking the ``item`` that returns True to
                skip processing, leaving the original item unchanged (default:
                None).

        Raises:
            TypeError: When an operator-only option (``embed``) is passed, since
                a processor never reads it.

        Examples:
            >>> from riko import async_return, issync, run
            >>>
            >>> @processor()
            ... def pipe(item, extraction, objconf, **kwargs):
            ...     content = item["content"]
            ...     return f'say "{content}" {objconf.times} times!'
            >>>
            >>> @processor()
            ... async def async_pipe(item, extraction, objconf, **kwargs):
            ...     content = await async_return(item["content"])
            ...     return f'say "{content}" {objconf.times} times!'
            >>>
            >>> item = {"content": "hello world"}
            >>> kwargs = {"conf": {"times": "three"}, "assign": "content"}
            >>> next(pipe(item, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>> async def main():
            ...     result = await async_pipe(item, **kwargs)
            ...     print(next(result))
            >>>
            >>> if issync:
            ...     {"content": 'say "hello world" three times!'}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}

        """
        _reject_foreign_opts("processor", _PROCESSOR_FORBIDDEN_OPTS, kwargs)
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def parse(self, item: ItemOrValue, module_name: str) -> DotDict[RikoValue]:
        """
        Normalizes a single input item into a ``DotDict``.

        ``None`` becomes an empty item (so source pipes still fire), a mapping is
        wrapped directly, and any other value is placed under ``"content"``.

        Args:
            item: The raw input item or value.
            module_name: The pipe's module name (currently unused).

        Returns:
            The item as a ``DotDict``.

        """
        if item is None:
            parsed: DotDict[RikoValue] = DotDict()
        elif is_mapping(item):
            parsed = DotDict(item)
        else:
            parsed = DotDict({"content": item})

        return parsed

    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: DotDict[RikoValue],
        field: str | None = None,
        **kwargs: ItemOrValue,
    ) -> tuple[ItemOrValue, Casted[T, E] | Casted[ItemOrValue, E], bool]:
        """
        Extracts and casts the input for a processor call.

        Uses the module's precomputed static cast when the conf does not vary per
        item, else parses and casts per call. Also resolves the per-item ``skip``.

        Args:
            prepared: The immutable per-call state from ``prepare``.
            input_: The parsed input item.
            field: Optional field whose value replaces the whole item.
            **kwargs: Extra call-time options forwarded to parsing.

        Returns:
            The original item, the cast field/extraction/conf, and the skip flag.

        """
        skip = get_skip(input_, skip_if=prepared.opts.get("skip_if"))

        if prepared.static_casted:
            field_func, pre_casted_extract, pre_casted_conf = prepared.static_casted
            field = field or prepared.opts.get("field", "")
            parsed_field = get_field(input_, field=field, **kwargs)
            casted_field = field_func(parsed_field)
            orig_item = input_
            casted = Casted(casted_field, pre_casted_extract, pre_casted_conf)
        else:
            args = (input_, prepared.opts, prepared.conf)
            orig_item, casted = parse_and_cast(
                *args,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=self.defaults,
                field=field,
                pipe=prepared.name,
                **kwargs,
            )

        return orig_item, casted, skip

    @overload
    def process(  # noqa: E704
        self,
        input_: DotDict[RikoValue],
        stream: Stream | DotDict[RikoValue],
        assign: str,
        emit: bool = ...,
        skip: bool = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        input_: DotDict[RikoValue],
        stream: ProcessorParserOutput,
        assign: str,
        emit: Literal[False] = ...,
        skip: Literal[False] = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        input_: DotDict[RikoValue],
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        skip: Literal[False] = ...,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        input_: DotDict[RikoValue],
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[False] = ...,
        *,
        skip: Literal[True],
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        input_: DotDict[RikoValue],
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        skip: Literal[True],
        count: CountValues | None = None,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        input_: DotDict[RikoValue],
        stream: ProcessorParserOutput,
        assign: str,
        emit: bool = ...,
        skip: bool = ...,
        count: CountValues | None = None,
    ) -> ProcessorWrapperOutput: ...
    def process(  # noqa: E301
        self,
        input_: DotDict[RikoValue],
        stream: ProcessorParserOutput,
        assign: str,
        emit: bool = False,
        skip: bool = False,
        count: CountValues | None = None,
    ) -> ProcessorWrapperOutput:
        """
        Assigns a parser's result back into the stream.

        On ``emit`` or ``skip`` the value passes straight through; otherwise the
        result is merged into the item under ``assign``.

        Args:
            input_: The original input item to merge into.
            stream: The parser's output.
            assign: The field the result is assigned to.
            emit: Whether to emit the result rather than assign it.
            skip: Whether the item was skipped (passed through unchanged).
            count: Optional stream-count reduction.

        Returns:
            The resulting stream.

        """
        if skip or emit:
            _, result = get_assignment(stream, skip=skip, count=count)
        else:
            one, assignment = get_assignment(stream, skip=False, count=count)
            result = gen_assignments(input_, assignment, assign=assign, one=one)

        return result

    @overload
    def __call__[T, E](  # noqa: E704
        self: "processor[Literal[True]]", pipe: AsyncProcessorParser[T, E]
    ) -> AsyncProcessorWrapper: ...
    @overload  # noqa: E301
    def __call__[T, E](  # noqa: E704
        self: "processor[Literal[False]]", pipe: AwaitableProcessorParser[T, E]
    ) -> AsyncProcessorWrapper: ...
    @overload  # noqa: E301
    def __call__[T, E](  # noqa: E704
        self: "processor[Literal[False]]", pipe: SyncProcessorParser[T, E]
    ) -> SyncProcessorWrapper: ...
    def __call__[T, E](self, pipe: ProcessorParser[T, E]) -> ProcessorWrapper:  # noqa: E301
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
        module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            item: ProcessorWrapperInput | None = None,
            conf: Conf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            **kwargs: bool,
        ) -> ProcessorWrapperOutput:
            if is_listlike(item):
                _wrapper = partial(
                    async_wrapper,
                    conf=conf,
                    context=context,
                    assign=assign,
                    field=field,
                    count=count,
                    mode=mode,
                    inputs=inputs,
                    **kwargs,
                )

                mapped = await async_map(_wrapper, item)
                processed = chain.from_iterable(mapped)
            else:
                input_ = self.parse(cast(ItemOrValue, item), module_name)
                prepared = self.prepare(
                    module_name, conf=conf, assign=assign, count=count, **kwargs
                )
                assign = prepared.assign
                orig_item, casted, skip = self.setup(
                    prepared, input_, field=field, count=count, **kwargs
                )

                if skip:
                    args = (input_, orig_item, assign)
                    processed = self.process(*args, emit=True, skip=True)
                else:
                    aync_pipe = cast(AsyncProcessorParser[T, object], pipe)
                    context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
                    inputs = context.inputs
                    kwargs["test"] = context.test
                    pkwargs = _call_kwargs(prepared, context, count, kwargs)
                    typed_casted = cast(Casted[T, E], casted)
                    result = aync_pipe(
                        typed_casted.field,
                        typed_casted.extraction,
                        typed_casted.conf,
                        **pkwargs,
                    )
                    stream = (await result) if isawaitable(result) else result
                    args = (input_, stream, assign)

                    if callable(prepared.emit) and not isinstance(stream, Iterator):
                        emit = prepared.emit(stream)
                    else:
                        emit = bool(prepared.emit)

                    if emit:
                        processed = self.process(
                            *args, emit=True, skip=False, count=count
                        )
                    else:
                        processed = self.process(
                            *args, emit=False, skip=False, count=count
                        )

            return processed

        def sync_wrapper(
            item: ProcessorWrapperInput | None = None,
            conf: Conf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            **kwargs: bool,
        ) -> ProcessorWrapperOutput:
            if is_listlike(item):
                _wrapper = partial(
                    sync_wrapper,
                    conf=conf,
                    context=context,
                    assign=assign,
                    field=field,
                    count=count,
                    mode=mode,
                    inputs=inputs,
                    **kwargs,
                )

                processed = chain.from_iterable(map(_wrapper, item))
            else:
                input_ = self.parse(cast(ItemOrValue, item), module_name)
                prepared = self.prepare(
                    module_name, conf=conf, assign=assign, count=count, **kwargs
                )
                assign = prepared.assign
                orig_item, casted, skip = self.setup(
                    prepared, input_, field=field, **kwargs
                )

                if skip:
                    args = (input_, orig_item, assign)
                    processed = self.process(*args, emit=True, skip=True)
                else:
                    sync_pipe = cast(SyncProcessorParser[T, E], pipe)
                    context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
                    inputs = context.inputs
                    kwargs["test"] = context.test
                    pkwargs = _call_kwargs(prepared, context, count, kwargs)
                    typed_casted = cast(Casted[T, E], casted)
                    stream = sync_pipe(
                        typed_casted.field,
                        typed_casted.extraction,
                        typed_casted.conf,
                        **pkwargs,
                    )
                    args = (input_, stream, assign)

                    if callable(prepared.emit) and not isinstance(stream, Iterator):
                        emit = prepared.emit(stream)
                    else:
                        emit = bool(prepared.emit)

                    if emit:
                        processed = self.process(
                            *args, emit=True, skip=False, count=count
                        )
                    else:
                        processed = self.process(
                            *args, emit=False, skip=False, count=count
                        )

            yield from processed

        isasync = self._resolve_isasync(pipe)
        wrapper = wraps(pipe)(async_wrapper if isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe, isasync)
        return cast(ProcessorWrapper, wrapper)


class operator[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    """Creates a pipe that processes an entire stream."""

    isasync: B
    module_type: ClassVar[ModuleType] = "operator"

    @overload
    def __init__(  # noqa: E704
        self: "operator[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "operator[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> None: ...
    def __init__(self, *args: object, **kwargs: object):  # noqa: E301
        """
        Configures a sync/async pipe that processes an entire stream.

        Args:
            defaults (dict): Default ``conf`` values (default: None).

        Kwargs:
            isasync (bool): Wraps an async pipe (default: False).

            pollable (bool): Marks the pipe as pollable for discovery (default: False).

            conf (dict): The pipe configuration; may contain an ``embed``
                sub-pipe (default: None).

            extract (str): Key whose ``conf`` values are passed to the pipe in
                place of ``conf`` (default: None).

            listize (bool): Ensure an ``extract`` value is list-like (default:
                False).

            objectify (bool): Convert ``conf`` to a ``meza.fntools.Objectify``
                instance (default: True unless ``ptype`` is ``"none"``).

            ptype (str): Converts ``conf`` items to a type after objectifying.
                One of ``"pass"``, ``"none"``, ``"text"``, ``"int"``,
                ``"float"``, or ``"decimal"``; ``"none"`` disables ``objectify``
                (default: "pass").

            field (str): Key whose ``items`` values are passed to the pipe in
                place of ``items`` (default: None).

            ftype (str): Converts the input ``items`` to a type after reading
                ``field``. Same choices as ``ptype`` (default: "pass").

            count (str): Stream count, ``"first"`` (first result only) or
                ``"all"`` (all results in a list) (default: None).

            assign (str): Field the stream is assigned to (default: the pipe
                name). Ignored when ``emit`` is true.

            embed (dict): Sub-pipe descriptor; must have ``"type"`` and may have
                ``"conf"`` (default: None).

            emit (bool): Return the stream as is instead of assigning it.
                Overrides ``assign`` (default: derived from ``ftype``).

        Raises:
            TypeError: When a processor-only option (``skip_if``) is passed,
                since an operator never reads it.

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
            ...     r1 = await async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = await async_pipe2(items, **kwargs)
            ...     print(next(r2))
            >>>
            >>> if issync:
            ...     {"content": 'say "hello world" three times!'}
            ...     {"content": 4}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        _reject_foreign_opts("operator", _OPERATOR_FORBIDDEN_OPTS, kwargs)
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def parse(self, items: OperatorWrapperInput | None = None) -> Stream:
        """
        Normalizes a sync input stream into ``DotDict`` items.

        Non-mapping elements are placed under ``"content"``; an empty or ``None``
        input yields nothing.

        Args:
            items: The source items, if any.

        Yields:
            Each input element as a ``DotDict``.

        """
        if items:
            for item in items:
                if is_mapping(item):
                    yield DotDict(item)
                else:
                    yield DotDict({"content": item})

    async def aparse(self, items: AsyncItemsOrValues) -> AsyncStream:
        """
        Normalizes an async input stream into ``DotDict`` items.

        The async counterpart of ``parse``; a lazy pass-through that never drains
        the source, so composer operators can bound an infinite ``Feed``.

        Args:
            items: The async source items.

        Yields:
            Each input element as a ``DotDict``.

        """
        async for item in items:
            if is_mapping(item):
                yield DotDict(item)
            else:
                yield DotDict({"content": item})

    def setup[T, E](
        self,
        prepared: PreparedModule[T, E],
        input_: Stream | AsyncStream,
        field: str | None = None,
        **kwargs: object,
    ) -> tuple[PipeTuples, Stream, Casted[Item, E] | Casted[T, E]]:
        """
        Builds the per-item tuples and original stream for an operator call.

        The two returned iterators are lazy views over one shared input: a parser reads
        whichever it needs, never both. ``tuples`` pairs each item with its own config
        (``(item, objconf)``) and serves a parser that reads config per item;
        ``orig_stream`` is just the items and serves a parser that applies one config
        to the whole stream (it may also carry terminal input). The precomputed static
        cast is reused when the config does not vary per item.

        Args:
            prepared: The immutable per-call state from ``prepare``.
            input_: The parsed sync or async input stream.
            field: Optional field whose value replaces each item.
            **kwargs: Extra call-time options forwarded to parsing.

        Returns:
            The per-item tuples, the original stream, and the cast extraction/conf.

        """
        if prepared.static_casted:
            _, pre_casted_extract, pre_casted_conf = prepared.static_casted
            objconf = pre_casted_conf
            item = cast(Item, DotDict())
            casted = Casted(item, pre_casted_extract, pre_casted_conf)

            if isinstance(input_, AsyncIterator):
                orig_stream = cast(Stream, input_)
                tuples = cast(PipeTuples, ((item, objconf) async for item in input_))
            else:
                orig_stream = input_
                tuples = ((item, objconf) for item in input_)
        else:
            _dispatcher: Callable[..., ItemDispatch] = partial(
                parse_and_cast,
                conf=prepared.conf,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=self.defaults,
                field=field,
                pipe=prepared.name,
            )
            # Parses conf that can vary per item. Can't handle terminal input
            dispatcher = cast(Callable[[Item, Opts], ItemDispatch[T, E]], _dispatcher)

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and full objconf
            # - orig_stream parses conf that doesn't vary per item; may hold input
            if isinstance(input_, AsyncIterator):
                adispatches = (dispatcher(item, prepared.opts) async for item in input_)
                tuples = cast(
                    PipeTuples, ((d.item, d.casted.conf) async for d in adispatches)
                )
                orig_stream = cast(Stream, (d.item async for d in adispatches))
            else:
                dispatches = (dispatcher(item, prepared.opts) for item in input_)
                tuples = ((d.item, d.casted.conf) for d in dispatches)
                orig_stream = (d.item for d in dispatches)

            item = cast(Item, DotDict())
            casted = dispatcher(item, prepared.opts, **kwargs).casted

        return (tuples, orig_stream, casted)

    @overload
    def process(  # noqa: E704
        self, stream: Stream | Iterator[StatefulItem], assign: str, emit: bool = ...
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: Literal[False] = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self, stream: PrimitiveValue, assign: str, emit: Literal[True]
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: bool = ...,
    ) -> OperatorWrapperOutput: ...
    def process(  # noqa: E301
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: bool = False,
    ) -> OperatorWrapperOutput:
        """
        Assigns an operator parser's result into a single-item stream.

        Operators nest: on ``emit`` the value passes through, otherwise it is
        assigned under ``assign`` into a fresh empty item (never merged).

        Args:
            stream: The parser's output.
            assign: The field the result is assigned to.
            emit: Whether to emit the result rather than assign it.

        Returns:
            The resulting stream.

        """
        items = stream
        one, assignment = get_assignment(items, skip=False)

        if emit:
            result = assignment
        else:
            result = gen_assignments(DotDict(), assignment, assign=assign, one=one)

        return result

    @overload
    def __call__[E](  # noqa: E704
        self: "operator[Literal[True]]", pipe: AsyncOperatorParser[E]
    ) -> AsyncOperatorWrapper: ...
    @overload  # noqa: E301
    def __call__[E](  # noqa: E704
        self: "operator[Literal[False]]", pipe: AwaitableOperatorParser[E]
    ) -> AsyncOperatorWrapper: ...
    @overload  # noqa: E301
    def __call__[E](  # noqa: E704
        self: "operator[Literal[False]]", pipe: SyncOperatorParser[E]
    ) -> SyncOperatorWrapper: ...
    def __call__[E](self, pipe: OperatorParser[E]) -> OperatorWrapper:  # noqa: E301
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
            ...     r1 = await wrapped_async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = await wrapped_async_pipe2(items, **kwargs)
            ...     print(next(r2))
            >>>
            >>> if issync:
            ...     {"content": 'say "hello world" three times!'}
            ...     {"content": 4}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        module_name = pipe.__module__.split(".")[-1]
        is_loop = module_name == "loop"

        async def async_wrapper(
            items: OperatorWrapperInput | Feed | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            embed: AsyncProcessorWrapper | AsyncSubPipe | None = None,
            **kwargs: bool,
        ) -> OperatorWrapperOutput:
            if isinstance(items, AsyncIterable):
                input_ = self.aparse(items)
            else:
                input_ = self.parse(items)

            prepared = self.prepare(
                module_name, conf=conf, assign=assign, count=count, **kwargs
            )
            assign = prepared.assign

            if is_loop:
                embedded_kwargs = EmbedKwargs(conf=prepared.conf, emit=True)
            else:
                embedded_kwargs = None

            context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
            inputs = context.inputs
            tuples, orig_stream, casted = self.setup(
                prepared, input_, inputs=inputs, field=field, count=count, **kwargs
            )
            handled, looped, embed_stream = loop_embed_async(
                embed,
                embedded_kwargs,
                context,
                cast(Stream, input_),
                module_name,
                field=field,
                assign=assign,
                emit=bool(prepared.emit),
                count=count,
            )

            if looped:
                processed = cast(StreamOrValueStream, embed_stream)
            elif handled:
                processed = cast(Stream, embed_stream)
            else:
                async_pipe = cast(AsyncOperatorParser[E], pipe)
                pkwargs = _call_kwargs(prepared, context, count, kwargs)
                extraction = cast(E, casted.extraction)
                result = async_pipe(orig_stream, extraction, tuples, **pkwargs)
                stream = (await result) if isawaitable(result) else result

                if isinstance(stream, Iterator):
                    emit = bool(prepared.emit)
                elif callable(prepared.emit):
                    emit = prepared.emit(stream)
                else:
                    emit = bool(prepared.emit)

                processed = self.process(stream, assign, emit=emit)

            return processed

        def sync_wrapper(
            items: OperatorWrapperInput | None = None,
            conf: Conf | DynamicConf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            embed: SyncProcessorWrapper | SyncSubPipe | None = None,
            **kwargs: bool,
        ) -> OperatorWrapperOutput:
            input_ = self.parse(items)
            prepared = self.prepare(
                module_name, conf=conf, assign=assign, count=count, **kwargs
            )
            assign = prepared.assign

            if is_loop:
                embedded_kwargs = EmbedKwargs(conf=prepared.conf, emit=True)
            else:
                embedded_kwargs = None

            context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
            inputs = context.inputs
            tuples, orig_stream, casted = self.setup(
                prepared, input_, inputs=inputs, field=field, count=count, **kwargs
            )
            handled, looped, embed_stream = loop_embed_sync(
                embed,
                embedded_kwargs,
                context,
                input_,
                module_name,
                field=field,
                assign=assign,
                emit=bool(prepared.emit),
                count=count,
            )

            if looped:
                processed = cast(StreamOrValueStream, embed_stream)
            elif handled:
                processed = embed_stream
            else:
                sync_pipe = cast(SyncOperatorParser[E], pipe)
                pkwargs = _call_kwargs(prepared, context, count, kwargs)
                extraction = cast(E, casted.extraction)
                stream = sync_pipe(orig_stream, extraction, tuples, **pkwargs)

                if isinstance(stream, Iterator):
                    emit = bool(prepared.emit)
                elif callable(prepared.emit):
                    emit = prepared.emit(stream)
                else:
                    emit = bool(prepared.emit)

                processed = self.process(stream, assign, emit=emit)

            yield from processed

        if isasync := self._resolve_isasync(pipe):
            wrapper = wraps(pipe)(async_wrapper)
        else:
            wrapper = wraps(pipe)(sync_wrapper)

        self._set_wrapper_metadata(wrapper, pipe, isasync)
        return cast(OperatorWrapper, wrapper)


class splitter[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    """Creates a pipe that splits a stream into multiple streams."""

    isasync: B
    module_type: ClassVar[ModuleType] = "splitter"

    @overload
    def __init__(  # noqa: E704
        self: "splitter[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        **kwargs: object,
    ) -> None: ...
    @overload  # noqa: E301
    def __init__(  # noqa: E704
        self: "splitter[Literal[False]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[False] = ...,
        **kwargs: object,
    ) -> None: ...
    def __init__(self, *args: object, **kwargs: object):  # noqa: E301
        """
        Configures a sync/async pipe that splits a stream into copies.

        Args:
            defaults (dict): Default ``conf`` values (default: None).

        Kwargs:
            isasync (bool): Wraps an async pipe (default: False).

            conf (dict): The pipe configuration (default: None).

            extract (str): Key whose ``conf`` value is passed to the pipe in
                place of ``conf`` (default: None).

            listize (bool): Ensure an ``extract`` value is list-like (default:
                False).

            objectify (bool): Convert ``conf`` to a ``meza.fntools.Objectify``
                instance (default: True unless ``ptype`` is ``"none"``).

            ptype (str): Converts ``conf`` items to a type after objectifying
                (default: "pass").

            field (str): Key whose ``items`` value is passed to the pipe in
                place of ``items`` (default: None).

            ftype (str): Converts the input ``items`` to a type after reading
                ``field`` (default: "pass").

            assign (str): Field the streams are assigned to (default: the pipe
                name).

        Raises:
            TypeError: When a processor/operator-only option (``pollable``,
                ``emit``, ``count``, ``skip_if``, ``embed``) is passed, since a
                splitter never reads any of them.

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
        _reject_foreign_opts("splitter", _SPLITTER_FORBIDDEN_OPTS, kwargs)
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def parse(self, items: SplitterWrapperInput | None = None) -> Stream:
        """
        Normalizes an input stream into ``DotDict`` items.

        Non-mapping elements are placed under ``"content"``; an empty or ``None``
        input yields nothing.

        Args:
            items: The source items, if any.

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
    ) -> tuple[PipeTuples, Stream, Casted[T, E]]:
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
            **kwargs: Extra call-time options forwarded to parsing.

        Returns:
            The per-item tuples, the original stream, and the cast extraction/conf.

        """
        _dispatcher = partial(
            parse_and_cast,
            conf=prepared.conf,
            parsers=prepared.parsers,
            casters=prepared.casters,
            defaults=self.defaults,
            field=field,
        )
        dispatcher = cast(Callable[[ItemOrValue, Opts], ItemDispatch], _dispatcher)
        dispatches = (dispatcher(item, prepared.opts) for item in input_)
        tuples = ((d.item, d.casted.conf) for d in dispatches)
        orig_stream = (d.item for d in dispatches)
        casted = dispatcher(DotDict(), prepared.opts, **kwargs).casted
        return (tuples, orig_stream, casted)

    @overload
    def __call__[E](  # noqa: E704
        self: "splitter[Literal[True]]", pipe: AsyncSplitterParser[E]
    ) -> AsyncSplitterWrapper: ...
    @overload  # noqa: E301
    def __call__[E](  # noqa: E704
        self: "splitter[Literal[False]]", pipe: AwaitableSplitterParser[E]
    ) -> AsyncSplitterWrapper: ...
    @overload  # noqa: E301
    def __call__[E](  # noqa: E704
        self: "splitter[Literal[False]]", pipe: SyncSplitterParser[E]
    ) -> SyncSplitterWrapper: ...
    def __call__[E](self, pipe: SplitterParser[E]) -> SplitterWrapper:  # noqa: E301
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
        op_module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            items: SplitterWrapperInput | None = None,
            conf: Conf | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            **kwargs: bool,
        ) -> Streams:
            input_ = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, assign=assign, **kwargs)
            tuples, orig_stream, casted = self.setup(
                prepared, input_, field=field, **kwargs
            )
            async_pipe = cast(AsyncSplitterParser[E], pipe)
            extraction = cast(E, casted.extraction)
            result = async_pipe(orig_stream, extraction, tuples, **kwargs)
            return (await result) if isawaitable(result) else result

        def sync_wrapper(
            items: SplitterWrapperInput | None = None,
            conf: Conf | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            **kwargs: bool,
        ) -> Streams:
            input_ = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, assign=assign, **kwargs)
            tuples, orig_stream, casted = self.setup(
                prepared, input_, field=field, **kwargs
            )
            sync_pipe = cast(SyncSplitterParser[E], pipe)
            extraction = cast(E, casted.extraction)
            streams = sync_pipe(orig_stream, extraction, tuples, **kwargs)
            yield from streams

        isasync = self._resolve_isasync(pipe)
        wrapper = wraps(pipe)(async_wrapper if isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe, isasync)
        return cast(SplitterWrapper, wrapper)
