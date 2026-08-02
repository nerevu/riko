# vim: sw=4:ts=4:expandtab
"""
riko.modules._decorators
~~~~~~~~~~~~~~~~~~~~~~~~~
Pipe-authoring decorators: the ``Module`` base and the ``processor`` /
``operator`` / ``splitter`` decorators that wrap a pipe function into the
sync/async module callables the framework executes.
"""

from collections.abc import Callable, Iterator
from functools import partial, wraps
from inspect import isawaitable
from itertools import chain, islice
from logging import Logger
from typing import Literal, cast, overload

import pygogo as gogo

from riko import Context, DynamicConf
from riko.bado.itertools import async_map
from riko.cast import BasicCastType
from riko.context import ExecutionMode
from riko.dotdict import DotDict, is_mapping
from riko.modules._assignment import gen_assignments, get_assignment
from riko.modules._loop import loop_embed_async_eager, loop_embed_sync
from riko.modules._metadata import derive_loopable, derive_subtypes
from riko.modules._prepare import (
    PreparedModule,
    get_casters,
    get_parsers,
    get_pieces_or_conf,
    parse_and_cast,
)
from riko.parsers import get_field, get_skip
from riko.types.general import (
    AsyncOperatorParser,
    AsyncOperatorWrapper,
    AsyncProcessorParser,
    AsyncProcessorWrapper,
    AsyncSplitterParser,
    AsyncSplitterWrapper,
    Casted,
    Defaults,
    Item,
    ItemDispatch,
    ItemOrValue,
    OperatorParser,
    OperatorParserOutput,
    OperatorWrapper,
    OperatorWrapperInput,
    OperatorWrapperOutput,
    Opts,
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
    SyncOperatorParser,
    SyncOperatorWrapper,
    SyncProcessorParser,
    SyncProcessorWrapper,
    SyncSplitterParser,
    SyncSplitterWrapper,
    ValueStream,
)
from riko.types.modules import CountValues, LoopConf, ModuleType
from riko.types.values import Inputs, PrimitiveValue, RikoValue, StatefulItem
from riko.utils import dispatch, parse_context

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


class Module[B: (Literal[True], Literal[False])]:
    isasync: B

    @overload
    def __init__(  # noqa: E704
        self: "Module[Literal[True]]",
        defaults: Defaults | None = ...,
        *,
        isasync: Literal[True],
        pollable: bool = ...,
        debug: bool = ...,
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
        debug: bool = ...,
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
        debug: bool = False,
        ftype: BasicCastType = BasicCastType.PASS,
        ptype: BasicCastType = BasicCastType.PASS,
        **opts: object,
    ):
        # Only called once on pipe import
        self.defaults: Defaults = defaults or Defaults()
        self._opts: Opts = Opts(ftype=ftype, ptype=ptype)
        self._opts.update(cast(Opts, opts))
        self.debug: bool = debug
        self.isasync = isasync  # pyright: ignore[reportAttributeAccessIssue]
        self.pollable: bool = pollable
        self.types: set[str] = set()

    def _set_wrapper_metadata(
        self,
        wrapper: wraps,
        pipe: Pipeline | ProcessorParser | OperatorParser | SplitterParser,
    ) -> None:
        module_type = cast(ModuleType, type(self).__name__)

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
        setattr(wrapper, "isasync", self.isasync)  # noqa: B010
        setattr(wrapper, "loopable", loopable)  # noqa: B010

    def prepare(
        self,
        module_name: str,
        conf: DynamicConf | None = None,
        *,
        assign: str | None = "",
        emit: bool | None = None,
        **kwargs: object,
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

        module_conf = DotDict(self.defaults)
        module_conf.update(conf or {})
        _conf = cast(DynamicConf, module_conf.asdict())

        if _emit and assign and not callable(_emit):
            msg = f"Assign is set to {assign} for {module_name} but will be "
            msg += "overridden since emit is True."
            logger.warning(msg)

        opts["emit"] = _emit
        opts["assign"] = _assign
        opts.update(cast(Opts, kwargs))

        parsers, is_dynamic = get_parsers(opts, conf=_conf, **kwargs)
        static_casted = None

        if opts.get("ptype") == BasicCastType.NONE:
            casters = None
        else:
            casters = get_casters(opts)

            if casters and not is_dynamic:
                parsed_conf = parsers.conf_parser({})
                args = (parsed_conf, self.defaults, opts)
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
        )


class processor[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    isasync: B

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
            >>> from riko.bado import run, async_return, issync
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
            >>> async def main():
            ...     result = await async_pipe(item, **kwargs)
            ...     print(next(result))
            ...
            >>> if issync:
            ...     {'content': 'say "hello world" three times!'}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}

        """
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def parse(
        self, item: ProcessorWrapperInput | ItemOrValue, module_name: str
    ) -> DotDict[RikoValue]:
        if isinstance(item, Iterator):
            items = list(islice(item, 2))

            if len(items) > 1:
                msg = f"{module_name} received an Iterator of more than 1 item. "
                msg += "Did you forget to use a loop? Processing only the first "
                msg += "item."
                logger.error(msg)

            _parsed = self.parse(items[0], module_name) if items else DotDict()
            parsed = _parsed
        elif item is None:
            parsed: DotDict[RikoValue] = DotDict()
        elif is_mapping(item):
            parsed = DotDict(item)
        else:
            parsed = DotDict({"content": item})

        return parsed

    def setup(
        self,
        prepared: PreparedModule,
        _input: DotDict[RikoValue],
        field: str | None = None,
        **kwargs: ItemOrValue,
    ) -> tuple[ItemOrValue, Casted, bool]:
        skip = get_skip(_input, skip_if=prepared.opts.get("skip_if"))

        if prepared.static_casted:
            field_func, pre_casted_extract, pre_casted_conf = prepared.static_casted
            field = field or prepared.opts.get("field", "")
            parsed_field = get_field(_input, field=field, **kwargs)
            casted_field = field_func(parsed_field)
            orig_item = _input
            casted = Casted(casted_field, pre_casted_extract, pre_casted_conf)
        else:
            args = (_input, prepared.opts, prepared.conf)
            orig_item, casted = parse_and_cast(
                *args,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=self.defaults,
                field=field,
                **kwargs,
            )

        return orig_item, casted, skip

    @overload
    def process(  # noqa: E704
        self,
        _input: DotDict[RikoValue],
        stream: Stream | DotDict[RikoValue],
        assign: str,
        emit: bool = ...,
        skip: bool = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict[RikoValue],
        stream: ProcessorParserOutput,
        assign: str,
        emit: Literal[False] = ...,
        skip: Literal[False] = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict[RikoValue],
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        skip: Literal[False] = ...,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict[RikoValue],
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[False] = ...,
        *,
        skip: Literal[True],
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict[RikoValue],
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        skip: Literal[True],
        count: CountValues | None = None,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        _input: DotDict[RikoValue],
        stream: ProcessorParserOutput,
        assign: str,
        emit: bool = ...,
        skip: bool = ...,
        count: CountValues | None = None,
        conf: DynamicConf | None = ...,
    ) -> ProcessorWrapperOutput: ...
    def process(  # noqa: E301
        self,
        _input: DotDict[RikoValue],
        stream: ProcessorParserOutput,
        assign: str,
        emit: bool = False,
        skip: bool = False,
        count: CountValues | None = None,
        conf: DynamicConf | None = None,
    ) -> ProcessorWrapperOutput:
        if skip or emit:
            _, result = get_assignment(stream, skip=skip, conf=conf, count=count)
        else:
            one, assignment = get_assignment(stream, skip=False, conf=conf, count=count)
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
            >>> from riko.bado import run, issync
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
            >>> async def main():
            ...     result = await async_pipe(item, **kwargs)
            ...     print(next(result))
            ...
            >>> if issync:
            ...     print('say "hello world" three times!')
            ... else:
            ...     run(main)
            say "hello world" three times!

        """
        module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            item: ProcessorWrapperInput | None = None,
            conf: DynamicConf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            **kwargs: bool,
        ) -> ProcessorWrapperOutput:
            if isinstance(item, Iterator):
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
                _input = self.parse(item, module_name)
                prepared = self.prepare(
                    module_name, conf=conf, assign=assign, count=count, **kwargs
                )
                assign = prepared.assign
                orig_item, casted, skip = self.setup(
                    prepared, _input, field=field, count=count, **kwargs
                )

                if prepared.static_casted:
                    _conf = prepared.static_casted[2]
                else:
                    _conf = prepared.conf

                if skip:
                    args = (_input, orig_item, assign)
                    processed = self.process(*args, emit=True, skip=True, conf=_conf)
                else:
                    aync_pipe = cast(AsyncProcessorParser, pipe)
                    context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
                    inputs = context.inputs
                    kwargs["test"] = context.test
                    pkwargs: dict[str, object] = {
                        "inputs": inputs,
                        "count": count,
                        **kwargs,
                    }
                    result = aync_pipe(*casted, **pkwargs)
                    stream = (await result) if isawaitable(result) else result
                    args = (_input, stream, assign)

                    if callable(prepared.emit) and not isinstance(stream, Iterator):
                        emit = prepared.emit(stream)
                    else:
                        emit = bool(prepared.emit)

                    if emit:
                        processed = self.process(
                            *args, emit=True, skip=False, count=count, conf=_conf
                        )
                    else:
                        processed = self.process(
                            *args, emit=False, skip=False, count=count, conf=_conf
                        )

            return processed

        def sync_wrapper(
            item: ProcessorWrapperInput | None = None,
            conf: DynamicConf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            **kwargs: bool,
        ) -> ProcessorWrapperOutput:
            if isinstance(item, Iterator):
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
                _input = self.parse(item, module_name)
                prepared = self.prepare(
                    module_name, conf=conf, assign=assign, count=count, **kwargs
                )
                assign = prepared.assign
                orig_item, casted, skip = self.setup(
                    prepared, _input, field=field, **kwargs
                )

                if prepared.static_casted:
                    _conf = prepared.static_casted[2]
                else:
                    _conf = prepared.conf

                if skip:
                    args = (_input, orig_item, assign)
                    processed = self.process(*args, emit=True, skip=True, conf=_conf)
                else:
                    sync_pipe = cast(SyncProcessorParser, pipe)
                    context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
                    inputs = context.inputs
                    kwargs["test"] = context.test
                    pkwargs: dict[str, object] = {
                        "inputs": inputs,
                        "count": count,
                        **kwargs,
                    }
                    stream = sync_pipe(*casted, **pkwargs)
                    args = (_input, stream, assign)

                    if callable(prepared.emit) and not isinstance(stream, Iterator):
                        emit = prepared.emit(stream)
                    else:
                        emit = bool(prepared.emit)

                    if emit:
                        processed = self.process(
                            *args, emit=True, skip=False, count=count, conf=_conf
                        )
                    else:
                        processed = self.process(
                            *args, emit=False, skip=False, count=count, conf=_conf
                        )

            yield from processed

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe)
        return cast(ProcessorWrapper, wrapper)


class operator[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    isasync: B

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
            >>> from riko.bado import run, async_return, issync
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
            >>> async def main():
            ...     r1 = await async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = await async_pipe2(items, **kwargs)
            ...     print(next(r2))
            ...
            >>> if issync:
            ...     {'content': 'say "hello world" three times!'}
            ...     {'content': 4}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def parse(self, items: OperatorWrapperInput | None = None) -> Stream:
        if items:
            for item in items:
                if is_mapping(item):
                    yield DotDict(item)
                else:
                    yield DotDict({"content": item})

    def setup(
        self,
        prepared: PreparedModule,
        _input: Stream,
        field: str | None = None,
        **kwargs: object,
    ) -> tuple[PipeTuples, Stream, Casted]:
        if prepared.static_casted:
            _, pre_casted_extract, pre_casted_conf = prepared.static_casted
            objconf = pre_casted_conf
            casted = Casted({}, pre_casted_extract, pre_casted_conf)
            tuples = ((item, objconf) for item in _input)
            orig_stream = _input
        else:
            _dispatcher = partial(
                parse_and_cast,
                conf=prepared.conf,
                parsers=prepared.parsers,
                casters=prepared.casters,
                defaults=self.defaults,
                field=field,
            )
            # Parses conf that can vary per item. Can't handle terminal input
            dispatcher = cast(Callable[[Item, Opts], ItemDispatch], _dispatcher)
            dispatches = (dispatcher(item, prepared.opts) for item in _input)

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and full objconf
            tuples = ((d.item, d.casted.conf) for d in dispatches)

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
        conf: DynamicConf | None = ...,
        is_loop: bool = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: Literal[False] = ...,
        conf: DynamicConf | None = ...,
        is_loop: bool = ...,
    ) -> Stream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: PrimitiveValue,
        assign: str,
        emit: Literal[True],
        conf: DynamicConf | None = ...,
        is_loop: bool = ...,
    ) -> ValueStream: ...
    @overload  # noqa: E301
    def process(  # noqa: E704
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: bool = ...,
        conf: DynamicConf | None = ...,
        is_loop: bool = ...,
    ) -> OperatorWrapperOutput: ...
    def process(  # noqa: E301
        self,
        stream: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
        assign: str,
        emit: bool = False,
        conf: DynamicConf | None = None,
        is_loop: bool = False,
    ) -> OperatorWrapperOutput:
        items = stream
        one, assignment = get_assignment(items, skip=False, conf=conf, is_loop=is_loop)

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
            >>> from riko.bado import run, issync
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
            >>> async def main():
            ...     r1 = await wrapped_async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = await wrapped_async_pipe2(items, **kwargs)
            ...     print(next(r2))
            ...
            >>> if issync:
            ...     {'content': 'say "hello world" three times!'}
            ...     {'content': 4}
            ... else:
            ...     run(main)
            {'content': 'say "hello world" three times!'}
            {'content': 4}

        """
        op_module_name = pipe.__module__.split(".")[-1]
        is_loop = op_module_name == "loop"

        async def async_wrapper(
            items: OperatorWrapperInput | None = None,
            conf: DynamicConf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            embed: AsyncProcessorWrapper | None = None,
            **kwargs: bool,
        ) -> OperatorWrapperOutput:
            _input = self.parse(items)
            prepared = self.prepare(
                op_module_name, conf=conf, assign=assign, count=count, **kwargs
            )
            assign = prepared.assign
            _conf = cast(LoopConf, prepared.conf)
            embedded_kwargs = _conf.get("embed")
            count = count or (_conf.get("count") if is_loop else None)
            context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
            inputs = context.inputs
            tuples, orig_stream, casted = self.setup(
                prepared, _input, inputs=inputs, field=field, count=count, **kwargs
            )
            handled, looped, embed_stream = await loop_embed_async_eager(
                embed,
                embedded_kwargs,
                context,
                _input,
                op_module_name,
            )

            if handled:
                stream = embed_stream
            else:
                async_pipe = cast(AsyncOperatorParser, pipe)
                pkwargs: dict[str, object] = {
                    "inputs": inputs,
                    "count": count,
                    **kwargs,
                }
                result = async_pipe(orig_stream, casted.extraction, tuples, **pkwargs)
                stream = (await result) if isawaitable(result) else result

            if looped:
                processed = cast(StreamOrValueStream, stream)
            else:
                if isinstance(stream, Iterator):
                    emit = bool(prepared.emit)
                elif callable(prepared.emit):
                    emit = prepared.emit(stream)
                else:
                    emit = bool(prepared.emit)

                processed = self.process(
                    stream, assign, emit=emit, conf=prepared.conf, is_loop=is_loop
                )

            return processed

        def sync_wrapper(
            items: OperatorWrapperInput | None = None,
            conf: DynamicConf | None = None,
            context: Context | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            count: CountValues | None = None,
            mode: ExecutionMode | None = None,
            inputs: Inputs | None = None,
            embed: SyncProcessorWrapper | None = None,
            **kwargs: bool,
        ) -> OperatorWrapperOutput:
            _input = self.parse(items)
            prepared = self.prepare(
                op_module_name, conf=conf, assign=assign, count=count, **kwargs
            )
            assign = prepared.assign
            _conf = cast(LoopConf, prepared.conf)
            embedded_kwargs = _conf.get("embed")
            count = count or (_conf.get("count") if is_loop else None)
            context = parse_context(context, mode=mode, inputs=inputs, **kwargs)
            inputs = context.inputs
            stream = _input
            tuples, orig_stream, casted = self.setup(
                prepared, stream, inputs=inputs, field=field, count=count, **kwargs
            )
            handled, looped, embed_stream = loop_embed_sync(
                embed,
                embedded_kwargs,
                context,
                _input,
                op_module_name,
                field=field,
                assign=assign,
                emit=bool(prepared.emit),
                count=count,
            )

            if handled:
                stream = embed_stream
            else:
                sync_pipe = cast(SyncOperatorParser, pipe)
                pkwargs: dict[str, object] = {
                    "inputs": inputs,
                    "count": count,
                    **kwargs,
                }
                stream = sync_pipe(orig_stream, casted.extraction, tuples, **pkwargs)

            if looped:
                processed = cast(StreamOrValueStream, stream)
            else:
                if isinstance(stream, Iterator):
                    emit = bool(prepared.emit)
                elif callable(prepared.emit):
                    emit = prepared.emit(stream)
                else:
                    emit = bool(prepared.emit)

                processed = self.process(
                    stream, assign, emit=emit, conf=prepared.conf, is_loop=is_loop
                )

            yield from processed

        if self.isasync:
            wrapper = wraps(pipe)(async_wrapper)
        else:
            wrapper = wraps(pipe)(sync_wrapper)

        self._set_wrapper_metadata(wrapper, pipe)
        return cast(OperatorWrapper, wrapper)


class splitter[B: (Literal[True], Literal[False])](Module[B]):  # noqa: N801
    isasync: B

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
        Creates a sync/async pipe that splits an entire stream of items
        """
        super().__init__(*args, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def parse(self, items: SplitterWrapperInput | None = None) -> Stream:
        if items:
            for item in items:
                data = item if is_mapping(item) else {"content": item}
                yield DotDict(data)

    def setup(
        self,
        prepared: PreparedModule,
        _input: Stream | SplitterWrapperInput,
        field: str | None = None,
        **kwargs: object,
    ) -> tuple[PipeTuples, Stream, Casted]:
        _stream = _input
        _dispatcher = partial(
            parse_and_cast,
            conf=prepared.conf,
            parsers=prepared.parsers,
            casters=prepared.casters,
            defaults=self.defaults,
            field=field,
        )
        dispatcher = cast(Callable[[ItemOrValue, Opts], ItemDispatch], _dispatcher)
        dispatches = (dispatcher(item, prepared.opts) for item in _stream)
        tuples = ((d.item, d.casted.conf) for d in dispatches)
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
            conf: DynamicConf | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            **kwargs: bool,
        ) -> Streams:
            _input = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, assign=assign, **kwargs)
            stream = _input
            tuples, orig_stream, casted = self.setup(
                prepared, stream, field=field, **kwargs
            )
            async_pipe = cast(AsyncSplitterParser, pipe)
            result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            return (await result) if isawaitable(result) else result

        def sync_wrapper(
            items: SplitterWrapperInput | None = None,
            conf: DynamicConf | None = None,
            *,
            assign: str | None = None,
            field: str | None = None,
            **kwargs: bool,
        ) -> Streams:
            _input = self.parse(items)
            prepared = self.prepare(op_module_name, conf=conf, assign=assign, **kwargs)
            stream = _input
            tuples, orig_stream, casted = self.setup(
                prepared, stream, field=field, **kwargs
            )
            sync_pipe = cast(SyncSplitterParser, pipe)
            streams = sync_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            yield from streams

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        self._set_wrapper_metadata(wrapper, pipe)
        return cast(SplitterWrapper, wrapper)
