# vim: sw=4:ts=4:expandtab
"""
riko.modules
~~~~~~~~~~~~
"""

from collections.abc import Callable, Iterator
from copy import copy
from functools import partial, wraps
from inspect import isawaitable
from itertools import chain, islice
from typing import Literal, overload
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
    OperatorParser,
    OperatorParserOutput,
    OperatorWrapper,
    OperatorWrapperInput,
    OperatorWrapperOutput,
    Opts,
    ParseFuncs,
    ParserOutput,
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
from riko.types.modules import ConfValues, Embed
from riko.types.values import BasicReturn, PrimitiveValue, StatefulItem
from riko.utils import broadcast, dispatch

logger = gogo.Gogo(__name__, monolog=True).logger

# Operators
__aggregators__ = (
    "count",
    "sum",
    "timeout",
    "aggregate",
    # 'mean',
    # 'min',
    # 'max',
)

__composers__ = (
    "filter",
    "join",
    "loop",
    "reverse",
    "sort",
    "split",
    "tail",
    "truncate",
    "union",
    "uniq",
    # 'webservice',
)

# Processors (loopable)
__sources__ = (
    "csv",
    "feedautodiscovery",
    "fetch",
    "fetchdata",
    "fetchpage",
    "fetchsitefeed",
    "forever",
    "fetchtext",
    "fetchtable",
    "itembuilder",
    "rssitembuilder",
    "xpathfetchpage",
    # yql was shutdown in 2019. Find alternatives, e.g.,
    # https://github.com/firecrawl/firecrawl
    # "yql",
    "input",  # not loopable
)

__transformers__ = (
    "currencyformat",
    "datebuilder",
    "dateformat",
    "exchangerate",
    "geolocate",
    "hash",
    # 'locationextractor',
    # 'locationbuilder',
    "regex",
    "rename",
    "refind",
    "simplemath",
    "slugify",
    "strconcat",
    "strfind",
    # 'tokenizer' -> tokenizer
    # 'strregex' -> regex
    "strreplace",
    "strtransform",
    "subelement",
    "substr",
    "typecast",
    # 'termextractor',
    "tokenizer",
    # 'translate',
    "udf",
    "urlbuilder",
    "urlparse",
    # 'yahooshortcuts',
)

# __all__ = __aggregators__ + __composers__ + __sources__ + __transformers__


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
    **conf: ConfValues
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
        elif value_is_iterator:
            yield item | {assign: list(value)}
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
        self.opts = Opts()
        self._opts = Opts(ftype=ftype, ptype=ptype)
        self._opts.update(cast_type(Opts, opts))
        self.parsers = self.casters = None
        self.conf = None
        self.debug = debug
        self.isasync = isasync  # pyright: ignore[reportAttributeAccessIssue]
        self.pollable = pollable
        self.types = set()
        self.assign = ""
        self.emit: bool | Callable[[ParserOutput], bool] | None = None
        self.name = None
        self.is_source = False
        self.sub_type = None
        self._prepare_key: tuple | None = None
        self._static_casted: tuple | None = None

    def prepare(
        self,
        module_name: str,
        conf: Conf = None,
        assign: str = "",
        emit: bool | None = None,
        **kwargs,
    ):
        conf = conf or {}
        def_emit = self._opts.get("emit") if emit is None else emit
        def_assign = assign or self._opts.get("assign", "")
        self.name = module_name
        self.opts = Opts(self._opts)
        self.opts.setdefault("objectify", self._opts.get("ptype") != BasicCastType.NONE)
        self.conf = DotDict(cast_type(dict, self.defaults))
        self.conf.update(cast_type(dict, conf))

        _type_name = type(self).__name__

        if _type_name == "operator":
            self.emit = is_mapping if def_emit is None else def_emit
            self.assign = def_assign or module_name
        elif _type_name in {"processor", "splitter"}:
            self.is_source = self._opts.get("ftype") == BasicCastType.NONE

            if def_emit is None:
                self.emit = self.is_source or is_mapping
            else:
                self.emit = def_emit

            assignment = "content" if self.is_source else module_name
            self.assign = def_assign or assignment
            self.sub_type = "source" if self.is_source else "transformer"
        else:
            logger.error(f"Unknown module {self}.")

        key = (module_name, repr(conf))

        if key == self._prepare_key:
            return

        self._prepare_key = key
        _conf = cast_type(Conf, self.conf.asdict())

        if self.emit and assign and not callable(self.emit):
            msg = f"Assign is set to {assign} for {module_name} but will be "
            msg += "overridden since emit is True."
            logger.warning(msg)

        self.opts["emit"] = self.emit
        self.opts["assign"] = self.assign
        self.opts.update(cast_type(Opts, kwargs))
        self.parsers = get_parsers(self.opts, conf=_conf, **kwargs)

        if self.opts.get("ptype") == BasicCastType.NONE:
            self.casters = None
            self._static_casted = None
        else:
            self.casters = get_casters(self.opts)

            if self.casters and not isinstance(self.parsers.conf_parser, partial):
                parsed_conf = self.parsers.conf_parser({})
                args = (parsed_conf, self.defaults, self.opts)
                parsed = get_pieces_or_conf(*args)
                casted = dispatch(parsed, *self.casters[1:])
                self._static_casted = (self.casters[0], *casted)
            else:
                self._static_casted = None


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

    def setup(self, _input: DotDict, **kwargs) -> tuple[DotDict, Casted, bool]:
        skip = get_skip(_input, skip_if=self.opts.get("skip_if"))

        if self._static_casted:
            field_func, pre_casted_extract, pre_casted_conf = self._static_casted
            field = kwargs.pop("field", None) or self.opts.get("field") or ""
            parsed_field = get_field(_input, field=field, **kwargs)
            casted_field = field_func(parsed_field)
            orig_item = _input
            casted = Casted(casted_field, pre_casted_extract, pre_casted_conf)
        else:
            conf = cast_type(Conf, self.conf.asdict())
            args = (_input, self.opts, conf)
            orig_item, casted = _dispatch(
                *args,
                parsers=self.parsers,
                casters=self.casters,
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
            self.prepare(module_name, conf=conf, **kwargs)
            assign = self.assign
            orig_item, casted, skip = self.setup(_input, **kwargs)

            if self._static_casted:
                _conf = cast_type(dict[str, ConfValues], self._static_casted[2])
            else:
                _conf = cast_type(dict[str, ConfValues], self.conf.asdict())

            if skip:
                args = (_input, orig_item, assign)
                processed = self.process(*args, emit=True, skip=True, **_conf)
            else:
                aync_pipe = cast_type(AsyncProcessorParser, pipe)
                result = aync_pipe(*casted, **kwargs)
                stream = (await result) if isawaitable(result) else result
                args = (_input, stream, assign)

                if callable(self.emit) and not isinstance(stream, Iterator):
                    emit = self.emit(stream)
                else:
                    emit = bool(self.emit)

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
            self.prepare(module_name, conf=conf, **kwargs)
            assign = self.assign
            orig_item, casted, skip = self.setup(_input, **kwargs)

            if self._static_casted:
                _conf = cast_type(dict[str, ConfValues], self._static_casted[2])
            else:
                _conf = cast_type(dict[str, ConfValues], self.conf.asdict())

            if skip:
                args = (_input, orig_item, assign)
                processed = self.process(*args, emit=True, skip=True, **_conf)
            else:
                sync_pipe = cast_type(SyncProcessorParser, pipe)
                stream = sync_pipe(*casted, **kwargs)
                args = (_input, stream, assign)

                if callable(self.emit) and not isinstance(stream, Iterator):
                    emit = self.emit(stream)
                else:
                    emit = bool(self.emit)

                if emit:
                    processed = self.process(*args, emit=True, skip=False, **_conf)
                else:
                    processed = self.process(*args, emit=False, skip=False, **_conf)

            yield from processed

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        sub_type = (
            "source" if self._opts.get("ftype") == BasicCastType.NONE else "transformer"
        )
        setattr(wrapper, "type", "processor")  # noqa: B010
        setattr(wrapper, "name", pipe.__module__.split(".")[-1])  # noqa: B010
        setattr(wrapper, "sub_type", sub_type)  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
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
            ...     for item, objconf in tuples:
            ...         content = await async_return(item['content'])
            ...         return f'say "{content}" {objconf.times} times!'
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

    def setup(self, _input: Stream, **kwargs) -> tuple[PipeTuples, Stream, Casted]:
        if self._static_casted:
            _, pre_casted_extract, pre_casted_conf = self._static_casted
            objconf = cast_type(Objconf, pre_casted_conf)
            casted = Casted({}, pre_casted_extract, pre_casted_conf)
            tuples = ((item, objconf) for item in _input)
            orig_stream = _input
        else:
            conf = cast_type(Conf, self.conf.asdict())
            _dispatcher = partial(
                _dispatch,
                conf=conf,
                parsers=self.parsers,
                casters=self.casters,
                defaults=Defaults(self.defaults),
            )
            # Parses conf that can vary per item. Can't handle terminal input
            dispatcher = cast_type(Callable[[Item, Opts], Dispatched], _dispatcher)
            dispatches = (dispatcher(item, self.opts) for item in _input)

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and full objconf
            tuples = ((d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches)

            # Parses conf that doesn't vary per item and may contain terminal input
            orig_stream = (d.item for d in dispatches)
            casted = dispatcher(DotDict(), self.opts, **kwargs).casted

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
        _, assignment = get_assignment(stream, skip=False, **conf)

        if emit:
            result = assignment
        else:
            singles = (iter([v]) for v in assignment)
            assigned = (
                gen_assignments(DotDict(), s, assign=assign, one=True) for s in singles
            )
            result = chain.from_iterable(assigned)

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
            >>> from twisted.internet.defer import maybeDeferred
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
            ...     word_cnt = await maybeDeferred(sum, words)
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
            embed: ProcessorWrapper | None = None,
            context: Context | None = None,
            **kwargs,
        ) -> OperatorWrapperOutput:
            _input = self.parse(items)
            self.prepare(op_module_name, conf=conf, **kwargs)
            _conf = cast_type(dict[str, ConfValues], self.conf.asdict())
            assign = self.assign
            embedded_kwargs = cast_type(Embed, self.conf.pop("embed", None))
            context = context or Context()

            if context.submodule:
                context.inputs = kwargs.get("inputs")

            stream = cast_type(OperatorWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(stream, **kwargs)

            if embed and getattr(embed, "name") == "input":  # noqa: B009
                logger.error("Embedding input pipes is not currently supported.")
            elif embed and getattr(embed, "type") == "processor":  # noqa: B009
                embed_context = copy(context)
                embed_context.submodule = True
                embedded_kwargs["context"] = embed_context
                embed = cast_type(AsyncProcessorWrapper, embed)
                embedder = partial(embed, **embedded_kwargs)
                stream_map = await async_map(embedder, _input)
                stream = cast_type(
                    ProcessorParserOutput, chain.from_iterable(stream_map)
                )
            elif embed:
                msg = "Only processor pipes can be embedded."
                msg = "Got {type} pipe {name}.".format(**embed.__dict__)
                logger.error(msg)
            elif op_module_name == "loop":
                logger.error("No embedded pipe provided!")
            else:
                async_pipe = cast_type(AsyncOperatorParser, pipe)
                result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
                stream = (await result) if isawaitable(result) else result

            if isinstance(stream, Iterator):
                emit = bool(self.emit)
                self.sub_type = "composer"
            else:
                emit = self.emit(stream) if callable(self.emit) else bool(self.emit)
                self.sub_type = "aggregator"

            setattr(async_wrapper, "sub_type", self.sub_type)  # noqa: B010

            if emit:
                processed = self.process(stream, assign, emit=True, **_conf)
            else:
                processed = self.process(stream, assign, emit=False, **_conf)

            return processed

        def sync_wrapper(
            items: OperatorWrapperInput | None = None,
            conf: Conf = None,
            embed: ProcessorWrapper | None = None,
            context: Context | None = None,
            **kwargs,
        ) -> OperatorWrapperOutput:
            _input = self.parse(items)
            self.prepare(op_module_name, conf=conf, **kwargs)
            _conf = cast_type(dict[str, ConfValues], self.conf.asdict())
            assign = self.assign
            embedded_kwargs = cast_type(Embed, self.conf.pop("embed", None))
            context = context or Context()

            if context.submodule:
                context.inputs = kwargs.get("inputs")

            stream = cast_type(OperatorWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(stream, **kwargs)

            if embed and getattr(embed, "name") == "input":  # noqa: B009
                logger.error("Embedding input pipes is not currently supported.")
            elif embed and getattr(embed, "type") == "processor":  # noqa: B009
                embed_context = copy(context)
                embed_context.submodule = True
                embedded_kwargs["context"] = embed_context
                embed = cast_type(SyncProcessorWrapper, embed)
                embedder = partial(embed, **embedded_kwargs)
                stream_map = map(embedder, _input)
                stream = cast_type(
                    ProcessorParserOutput, chain.from_iterable(stream_map)
                )
            elif embed:
                msg = "Only processor pipes can be embedded."
                msg = "Got {type} pipe {name}.".format(**embed.__dict__)
                logger.error(msg)
            elif op_module_name == "loop":
                logger.error("No embedded pipe provided!")
            else:
                sync_pipe = cast_type(SyncOperatorParser, pipe)
                stream = sync_pipe(orig_stream, casted.extraction, tuples, **kwargs)

            if isinstance(stream, Iterator):
                emit = bool(self.emit)
                self.sub_type = "composer"
            else:
                emit = self.emit(stream) if callable(self.emit) else bool(self.emit)
                self.sub_type = "aggregator"

            setattr(sync_wrapper, "sub_type", self.sub_type)  # noqa: B010

            if emit:
                processed = self.process(stream, assign, emit=True, **_conf)
            else:
                processed = self.process(stream, assign, emit=False, **_conf)

            yield from processed

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        setattr(wrapper, "type", "operator")  # noqa: B010
        setattr(wrapper, "name", pipe.__module__.split(".")[-1])  # noqa: B010
        setattr(wrapper, "sub_type", None)  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
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

    def setup(self, _input: Stream, **kwargs) -> tuple[PipeTuples, Stream, Casted]:
        conf = cast_type(Conf, self.conf.asdict())
        _dispatcher = partial(
            _dispatch,
            conf=conf,
            parsers=self.parsers,
            casters=self.casters,
            defaults=Defaults(self.defaults),
        )
        dispatcher = cast_type(Callable[[Item, Opts], Dispatched], _dispatcher)
        dispatches = (dispatcher(item, self.opts) for item in _input)
        tuples = ((d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches)
        orig_stream = (d.item for d in dispatches)
        casted = dispatcher(DotDict(), self.opts, **kwargs).casted
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
            self.prepare(op_module_name, conf=conf, **kwargs)
            stream = cast_type(SplitterWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(stream, **kwargs)
            async_pipe = cast_type(AsyncSplitterParser, pipe)
            result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            return (await result) if isawaitable(result) else result

        def sync_wrapper(
            items: SplitterWrapperInput | None = None,
            conf: Conf = None,
            **kwargs,
        ) -> Streams:
            _input = self.parse(items)
            self.prepare(op_module_name, conf=conf, **kwargs)
            stream = cast_type(SplitterWrapperInput, _input)
            tuples, orig_stream, casted = self.setup(stream, **kwargs)
            sync_pipe = cast_type(SyncSplitterParser, pipe)
            streams = sync_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            yield from streams

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        setattr(wrapper, "type", "splitter")  # noqa: B010
        setattr(wrapper, "name", pipe.__module__.split(".")[-1])  # noqa: B010
        setattr(wrapper, "sub_type", "splitter")  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
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
