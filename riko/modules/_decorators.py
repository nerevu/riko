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
from inspect import (
    isawaitable,
)
from itertools import chain, islice
from typing import (
    Literal,
    overload,
)
from typing import cast as cast_type

import pygogo as gogo

from riko import Context, DynamicConf
from riko.bado.itertools import async_map
from riko.cast import BasicCastType
from riko.dotdict import DotDict, is_mapping
from riko.modules._assignment import _get_subpipe, gen_assignments, get_assignment
from riko.modules._metadata import (
    _derive_loopable,
    _derive_subtypes,
)
from riko.modules._prepare import (
    PreparedModule,
    _dispatch,
    get_casters,
    get_parsers,
    get_pieces_or_conf,
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
    Conf,
    Defaults,
    Dispatched,
    Item,
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
    Streams,
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
    ModuleType,
)
from riko.types.values import (
    PrimitiveValue,
    StatefulItem,
)
from riko.utils import dispatch, parse_context

logger = gogo.Gogo(__name__, monolog=True).logger


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
            ...     print('say "hello world" three times!')
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
                kwargs["test"] = context.test
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
                kwargs["test"] = context.test
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
            objconf = cast_type(DynamicConf, pre_casted_conf)
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
            tuples = (
                (d.item, cast_type(DynamicConf, d.casted.conf)) for d in dispatches
            )

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
        tuples = ((d.item, cast_type(DynamicConf, d.casted.conf)) for d in dispatches)
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
