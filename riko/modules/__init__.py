# vim: sw=4:ts=4:expandtab
"""
riko.modules
~~~~~~~~~~~~
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from copy import copy
from functools import partial, wraps
from inspect import isawaitable
from itertools import chain
from time import struct_time
from typing import TypeVar, overload
from typing import cast as cast_type

import pygogo as gogo
from meza.process import merge

from riko import Context, Objconf, Objectify, listize, objectify
from riko.bado.itertools import async_map
from riko.cast import CAST_SWITCH, BasicCastType, CastType, cast_none, cast_pass
from riko.cast import cast as cast_value
from riko.dotdict import DotDict
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
    Defaults,
    Dispatched,
    ItemArg,
    OperatorItems,
    OperatorParser,
    OperatorWrapper,
    Opts,
    ParseFuncs,
    PipeTuples,
    ProcessorItems,
    ProcessorParser,
    ProcessorWrapper,
    SplitterItems,
    SplitterParser,
    SplitterWrapper,
    Stream,
    SyncOperatorParser,
    SyncOperatorWrapper,
    SyncProcessorParser,
    SyncProcessorWrapper,
    SyncSplitterParser,
    SyncSplitterWrapper,
)
from riko.types.modules import AnyModuleConf, Embed
from riko.types.values import (
    BasicArg,
    ComplexArg,
    ComplexValue,
    DateLike,
    DateLikeType,
    NumLike,
    NumLikeType,
    StreamState,
)
from riko.utils import broadcast, dispatch

logger = gogo.Gogo(__name__, monolog=True).logger

FRAMEWORK_KEYS = frozenset(
    {"isasync", "pollable", "debug", "ftype", "ptype", "assign", "emit"}
)

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

SENTINELS = {StreamState.DONE}

T = TypeVar("T", bound=ComplexArg)


def dictize(data: Mapping | T) -> DotDict | T:
    if isinstance(data, (DotDict, Objectify)):
        result = data
    elif isinstance(data, Mapping):
        result = DotDict(data)
    else:
        result = data

    return result


# TODO: figure out why type checker doesn't like Stream
def get_assignment(
    items: ProcessorItems | OperatorItems, conf: AnyModuleConf, skip=False
) -> tuple[bool, Stream]:
    count = conf.get("count")

    if isinstance(items, (str, int, struct_time)):
        dictized = iter([items])
    elif isinstance(items, Mapping):
        dictized = iter([dictize(items)])
    elif isinstance(items, Iterable):
        dictized = map(dictize, items)
    else:
        dictized = iter([items])

    if skip:
        one = False
        result = dictized
    else:
        try:
            first_result = next(dictized)
        except StopIteration:
            first_result = None

        try:
            second_result = next(dictized)
        except StopIteration:
            # pipe delivers one result, e.g., strconcat
            if first_result is None:
                result = iter([])
            else:
                result = chain([first_result], dictized)

            multiple = False
        else:
            # pipe delivers multiple results, e.g., fetchpage/tokenizer
            if first_result is None:
                result = chain([], [second_result], dictized)
            else:
                result = chain([first_result], [second_result], dictized)

            multiple = True

        first = bool(count == "first")
        _all = count == "all"
        one = first or not (multiple or _all)

        if one and first_result is not None:
            result = iter([first_result])
        elif one:
            result = iter([])

    return one, result


def gen_assignments(
    item: Mapping,
    assignment: ProcessorItems,
    one=False,
    assign: str | None = None,
    **_,
) -> Stream:
    if isinstance(assignment, Iterator):
        value = next(assignment, None) if one else assignment
    else:
        value = assignment

    if assign:
        if value is None:
            yield DotDict(item)
        elif isinstance(value, (str, int, struct_time, Mapping, Objectify)):
            merged = merge([item, {assign: value}])
            yield DotDict(merged)
        elif isinstance(value, Iterable):
            merged = merge([item, {assign: list(value)}])
            yield DotDict(merged)
        else:
            merged = merge([item, {assign: value}])
            yield DotDict(merged)
    elif isinstance(value, (str, int, struct_time)):
        yield value
    elif isinstance(value, Mapping):
        yield dictize(value)
    elif isinstance(value, Iterable):
        yield from map(dictize, value)
    else:
        yield value


def get_pieces_or_conf(
    parsed_conf: ComplexArg, defaults: Defaults, opts: Opts
) -> tuple[
    BasicArg | AnyModuleConf | list[BasicArg] | Defaults | None,
    AnyModuleConf | Defaults,
]:
    if isinstance(parsed_conf, Mapping):
        merged_conf = cast_type(AnyModuleConf, {**defaults, **parsed_conf})
    else:
        merged_conf = defaults

    if extract := opts.get("extract"):
        try:
            pieces = next(v for k, v in merged_conf.items() if k.lower() == extract)
        except StopIteration:
            logger.error(f"{extract=} not found in conf {merged_conf}")
            pieces = None
        else:
            pieces = cast_type(BasicArg, pieces)

        if pieces and opts.get("listize"):
            pieces_or_conf = cast_type(list[BasicArg], listize(pieces))
        else:
            pieces_or_conf = pieces
    else:
        pieces_or_conf = merged_conf

    return pieces_or_conf, merged_conf


class Module:
    def __init__(
        self,
        defaults: Defaults | None = None,
        /,
        isasync=False,
        pollable=False,
        *,
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
        self.isasync = isasync
        self.pollable = pollable
        self.types = set()
        self.assign = None
        self.emit = None
        self.name = None
        self.is_source = False
        self.sub_type = None
        self._prepare_key: tuple | None = None
        self._static_casted: tuple | None = None

    def prepare(
        self,
        module_name: str,
        conf: AnyModuleConf | None = None,
        assign: str | None = None,
        emit: bool | None = None,
        **kwargs,
    ):
        key = (module_name, repr(conf), assign, emit, tuple(sorted(kwargs.items())))

        if key == self._prepare_key:
            return

        self._prepare_key = key

        if emit is None:
            def_emit = self._opts.get("emit")
        else:
            def_emit = emit

        if assign is None:
            def_assign = self._opts.get("assign")
        else:
            def_assign = assign

        self.name = module_name

        self.opts = Opts(self._opts)
        self.opts.setdefault("objectify", self._opts.get("ptype") != "none")
        self.conf = DotDict(self.defaults)
        self.conf.update(conf)

        if "operator" in str(self):
            self.emit = True if def_emit is None else def_emit
            self.assign = None if self.emit else def_assign or module_name
        elif "processor" in str(self):
            self.is_source = self._opts.get("ftype") == "none"
            self.emit = self.is_source if def_emit is None else def_emit
            assignment = "content" if self.is_source else module_name
            self.assign = None if self.emit else def_assign or assignment
            self.sub_type = "source" if self.is_source else "transformer"
        else:
            logger.error(f"Unknown module {self}.")

        _conf = cast_type(AnyModuleConf, self.conf.asdict())
        self.opts.update(cast_type(Opts, kwargs))
        self.opts["emit"] = self.emit
        self.opts["assign"] = self.assign
        self.parsers = get_parsers(self.opts, conf=_conf)

        if self.opts.get("ptype") == "none":
            self.casters = None
            self._static_casted = None
        else:
            self.casters = get_casters(self.opts)

            if self.casters and not conf_is_dynamic(_conf):
                parsed_conf = parse_conf(None, conf=_conf)
                args = (parsed_conf, self.defaults, self.opts)
                parsed = get_pieces_or_conf(*args)
                casted = dispatch(parsed, *self.casters[1:])
                self._static_casted = (self.casters[0], *casted)
            else:
                self._static_casted = None


class processor(Module):  # noqa: N801
    def __init__(self, *args, **kwargs):
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
                attribute (default: True if `ftype` is set to 'none', False
                otherwise). Overrides `assign`.

            skip_if (func): A function that takes the `item` and should return
                True if processing should be skipped, or False otherwise. If
                processing is skipped, the resulting stream will be the original
                input `item`.

        Examples:
            >>> from riko.bado import react, util, _issync
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
            ...     content = await util.async_return(item['content'])
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

    def parse(self, item: ItemArg, module_name: str) -> DotDict | DateLike | NumLike:
        if isinstance(item, (NumLikeType, DateLikeType, DotDict)):
            parsed = item
        elif isinstance(item, Objectify):
            parsed = DotDict(dict(item.iteritems()))
        elif isinstance(item, Mapping):
            parsed = DotDict(item)
        elif isinstance(item, (Iterator, Sequence)):
            items = list(item)

            if (item_count := len(items)) > 1:
                msg = f"{module_name} received an Iterator of {item_count} items. "
                msg += "Did you forget to use a loop? Processing only the first "
                msg += "item."
                logger.error(msg)

            parsed = self.parse(items[0], module_name)
        else:
            parsed = DotDict()

        return parsed

    def setup(
        self, _input: DotDict | DateLike | NumLike, **kwargs
    ) -> tuple[ItemArg, Casted, bool]:
        dispatch_kwargs = {k: v for k, v in kwargs.items() if k not in FRAMEWORK_KEYS}
        skip = get_skip(_input, skip_if=self.opts.get("skip_if"))

        if self._static_casted:
            field_func, pre_casted_extract, pre_casted_conf = self._static_casted
            field = dispatch_kwargs.pop("field", None) or self.opts.get("field") or ""
            parsed_field = get_field(_input, field=field, **dispatch_kwargs)
            casted_field = field_func(parsed_field)
            orig_item = _input
            casted = Casted(casted_field, pre_casted_extract, pre_casted_conf)
        else:
            _conf = cast_type(AnyModuleConf, self.conf.asdict())
            args = (_input, self.opts, _conf)
            orig_item, casted = _dispatch(
                *args,
                parsers=self.parsers,
                casters=self.casters,
                defaults=Defaults(self.defaults),
                **dispatch_kwargs,
            )

        return orig_item, casted, skip

    def process(
        self,
        _input: DotDict | DateLike | NumLike,
        stream: ProcessorItems,
        emit: bool,
        assign: str,
        skip: bool,
        conf: AnyModuleConf,
    ) -> Stream:
        one, assignment = get_assignment(stream, conf, skip=skip)

        if skip or emit:
            result = assignment
        elif isinstance(_input, Mapping):
            result = gen_assignments(_input, assignment, one=one, assign=assign)
        else:
            result = assignment

        return result

    @overload
    def __call__(  # noqa: E704
        self, pipe: AsyncProcessorParser
    ) -> AsyncProcessorWrapper: ...
    @overload  # noqa: E301
    def __call__(  # noqa: E704
        self, pipe: SyncProcessorParser
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
            item: ItemArg = None,
            conf: AnyModuleConf | None = None,
            **kwargs,
        ) -> Stream:
            _input = self.parse(item, module_name)
            self.prepare(module_name, conf=conf, **kwargs)
            emit = bool(self.emit)
            assign = self.assign or ""
            orig_item, casted, skip = self.setup(_input, **kwargs)

            if self._static_casted:
                _conf = cast_type(AnyModuleConf, self._static_casted[2])
            else:
                _conf = cast_type(AnyModuleConf, self.conf.asdict())

            if skip:
                stream = orig_item
            else:
                aync_pipe = cast_type(AsyncProcessorParser, pipe)
                result = aync_pipe(*casted, **kwargs)
                stream = (await result) if isawaitable(result) else result

            return self.process(_input, stream, emit, assign, skip, _conf)

        def sync_wrapper(
            item: ItemArg = None,
            conf: AnyModuleConf | None = None,
            **kwargs,
        ) -> Stream:
            _input = self.parse(item, module_name)
            self.prepare(module_name, conf=conf, **kwargs)
            emit = bool(self.emit)
            assign = self.assign or ""
            orig_item, casted, skip = self.setup(_input, **kwargs)

            if self._static_casted:
                _conf = cast_type(AnyModuleConf, self._static_casted[2])
            else:
                _conf = cast_type(AnyModuleConf, self.conf.asdict())

            if skip:
                stream = orig_item
            else:
                sync_pipe = cast_type(SyncProcessorParser, pipe)
                stream = sync_pipe(*casted, **kwargs)

            yield from self.process(_input, stream, emit, assign, skip, _conf)

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        sub_type = "source" if self._opts.get("ftype") == "none" else "transformer"
        setattr(wrapper, "type", "processor")  # noqa: B010
        setattr(wrapper, "name", pipe.__module__.split(".")[-1])  # noqa: B010
        setattr(wrapper, "sub_type", sub_type)  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
        return cast_type(ProcessorWrapper, wrapper)


class operator(Module):  # noqa: N801
    def __init__(self, *args, **kwargs):
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
                attribute (default: True). Overrides `assign`.

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from riko.bado import react, util, _issync
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
            ...         content = await util.async_return(item['content'])
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

    def setup(self, _input, **kwargs) -> tuple[PipeTuples, Stream, Casted]:
        if self._static_casted:
            _, pre_casted_extract, pre_casted_conf = self._static_casted
            objconf = cast_type(Objconf, pre_casted_conf)
            casted = Casted({}, pre_casted_extract, pre_casted_conf)
            tuples = ((item, objconf) for item in _input)
            orig_stream = _input
        else:
            dispatch_kwargs = {
                k: v for k, v in kwargs.items() if k not in FRAMEWORK_KEYS
            }

            conf = cast_type(AnyModuleConf, self.conf.asdict())
            _dispatcher = partial(
                _dispatch,
                conf=conf,
                parsers=self.parsers,
                casters=self.casters,
                defaults=Defaults(self.defaults),
            )
            # Parses conf that can vary per item. Can't handle terminal input
            dispatcher = cast_type(Callable[[ItemArg, Opts], Dispatched], _dispatcher)
            dispatches = (dispatcher(item, self.opts) for item in _input)

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and full objconf
            tuples = ((d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches)

            # Parses conf that doesn't vary per item and may contain terminal input
            orig_stream = (d.item for d in dispatches)
            casted = dispatcher(DotDict(), self.opts, **dispatch_kwargs).casted

        return (tuples, orig_stream, casted)

    def process(self, stream, emit: bool, assign: str, conf: AnyModuleConf) -> Stream:
        _, assignment = get_assignment(stream, conf, skip=False)

        if emit:
            result = assignment
        else:
            singles = (iter([v]) for v in assignment)
            assigned = (
                gen_assignments({}, s, one=True, assign=assign) for s in singles
            )
            result = chain.from_iterable(assigned)

        return result

    @overload
    def __call__(  # noqa: E704
        self, pipe: AsyncOperatorParser
    ) -> AsyncOperatorWrapper: ...
    @overload  # noqa: E301
    def __call__(  # noqa: E704
        self, pipe: SyncOperatorParser
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
            items: Stream | None = None,
            conf: AnyModuleConf | None = None,
            embed: ProcessorWrapper | None = None,
            context: Context | None = None,
            **kwargs,
        ) -> OperatorItems:
            _input = map(dictize, iter(items or []))
            self.prepare(op_module_name, conf=conf, **kwargs)
            _conf = cast_type(AnyModuleConf, self.conf.asdict())
            emit = bool(self.emit)
            assign = self.assign or ""
            embedded_kwargs = cast_type(Embed, self.conf.pop("embed", None))
            context = context or Context()

            if context.submodule:
                context.inputs = kwargs.get("inputs")

            tuples, orig_stream, casted = self.setup(_input, **kwargs)

            if embed and getattr(embed, "name") == "input":  # noqa: B009
                logger.error("Embedding input pipes is not currently supported.")
                stream = _input
            elif embed and getattr(embed, "type") == "processor":  # noqa: B009
                embed_context = copy(context)
                embed_context.submodule = True
                embedded_kwargs["context"] = embed_context
                embed = cast_type(AsyncProcessorWrapper, embed)
                embedder = partial(embed, **embedded_kwargs)
                stream_map = await async_map(embedder, _input)
                stream = chain.from_iterable(stream_map)
            elif embed:
                msg = "Only processor pipes can be embedded."
                msg = "Got {type} pipe {name}.".format(**embed.__dict__)
                logger.error(msg)
                stream = map(dictize, iter(items or []))
            elif op_module_name == "loop":
                logger.error("No embedded pipe provided!")
                stream = map(dictize, iter(items or []))
            else:
                async_pipe = cast_type(AsyncOperatorParser, pipe)
                result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
                stream = (await result) if isawaitable(result) else result

            self.sub_type = "aggregator" if isinstance(stream, Mapping) else "composer"
            setattr(async_wrapper, "sub_type", self.sub_type)  # noqa: B010
            return self.process(stream, emit, assign, _conf)

        def sync_wrapper(
            items: Stream | None = None,
            conf: AnyModuleConf | None = None,
            embed: ProcessorWrapper | None = None,
            context: Context | None = None,
            **kwargs,
        ) -> OperatorItems:
            _input = map(dictize, iter(items or []))
            self.prepare(op_module_name, conf=conf, **kwargs)
            _conf = cast_type(AnyModuleConf, self.conf.asdict())
            emit = bool(self.emit)
            assign = self.assign or ""
            embedded_kwargs = cast_type(Embed, self.conf.pop("embed", None))
            context = context or Context()

            if context.submodule:
                context.inputs = kwargs.get("inputs")

            tuples, orig_stream, casted = self.setup(_input, **kwargs)

            if embed and getattr(embed, "name") == "input":  # noqa: B009
                logger.error("Embedding input pipes is not currently supported.")
                stream = _input
            elif embed and getattr(embed, "type") == "processor":  # noqa: B009
                embed_context = copy(context)
                embed_context.submodule = True
                embedded_kwargs["context"] = embed_context
                embed = cast_type(SyncProcessorWrapper, embed)
                embedder = partial(embed, **embedded_kwargs)
                stream_map = map(embedder, _input)
                stream = chain.from_iterable(stream_map)
            elif embed:
                msg = "Only processor pipes can be embedded."
                msg = "Got {type} pipe {name}.".format(**embed.__dict__)
                logger.error(msg)
                stream = _input
            elif op_module_name == "loop":
                logger.error("No embedded pipe provided!")
                stream = _input
            else:
                sync_pipe = cast_type(SyncOperatorParser, pipe)
                stream = sync_pipe(orig_stream, casted.extraction, tuples, **kwargs)

            self.sub_type = "aggregator" if isinstance(stream, Mapping) else "composer"
            setattr(sync_wrapper, "sub_type", self.sub_type)  # noqa: B010
            yield from self.process(stream, emit, assign, _conf)

        wrapper = wraps(pipe)(async_wrapper if self.isasync else sync_wrapper)
        setattr(wrapper, "type", "operator")  # noqa: B010
        setattr(wrapper, "name", pipe.__module__.split(".")[-1])  # noqa: B010
        setattr(wrapper, "sub_type", None)  # noqa: B010
        setattr(wrapper, "pollable", self.pollable)  # noqa: B010
        return cast_type(OperatorWrapper, wrapper)


class splitter(Module):  # noqa: N801
    def setup(self, _input, **kwargs) -> tuple[PipeTuples, Stream, Casted]:
        dispatch_kwargs = {k: v for k, v in kwargs.items() if k not in FRAMEWORK_KEYS}
        conf = cast_type(AnyModuleConf, self.conf.asdict())
        _dispatcher = partial(
            _dispatch,
            conf=conf,
            parsers=self.parsers,
            casters=self.casters,
            defaults=Defaults(self.defaults),
        )
        dispatcher = cast_type(Callable[[ItemArg, Opts], Dispatched], _dispatcher)
        dispatches = (dispatcher(item, self.opts) for item in _input)
        tuples = ((d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches)
        orig_stream = (d.item for d in dispatches)
        casted = dispatcher(DotDict(), self.opts, **dispatch_kwargs).casted
        return (tuples, orig_stream, casted)

    @overload
    def __call__(  # noqa: E704
        self, pipe: AsyncSplitterParser
    ) -> AsyncSplitterWrapper: ...
    @overload  # noqa: E301
    def __call__(  # noqa: E704
        self, pipe: SyncSplitterParser
    ) -> SyncSplitterWrapper: ...
    def __call__(self, pipe: SplitterParser) -> SplitterWrapper:  # noqa: E301
        op_module_name = pipe.__module__.split(".")[-1]

        async def async_wrapper(
            items: Stream | None = None,
            conf: AnyModuleConf | None = None,
            **kwargs,
        ) -> SplitterItems:
            _input = map(dictize, iter(items or []))
            self.prepare(op_module_name, conf=conf, **kwargs)
            tuples, orig_stream, casted = self.setup(_input, **kwargs)
            async_pipe = cast_type(AsyncSplitterParser, pipe)
            result = async_pipe(orig_stream, casted.extraction, tuples, **kwargs)
            return (await result) if isawaitable(result) else result

        def sync_wrapper(
            items: Stream | None = None,
            conf: AnyModuleConf | None = None,
            **kwargs,
        ) -> SplitterItems:
            _input = map(dictize, iter(items or []))
            self.prepare(op_module_name, conf=conf, **kwargs)
            tuples, orig_stream, casted = self.setup(_input, **kwargs)
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
    item: ItemArg,
    opts: Opts,
    conf: AnyModuleConf,
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
    conf = cast_type(AnyModuleConf, casted[2])
    return Dispatched(item, Casted(casted[0], casted[1], conf))


def get_parsers(opts: Opts, conf: AnyModuleConf) -> ParseFuncs:
    conf = conf or {}

    if opts.get("ftype") == "none":
        field_parser = cast_none
    else:
        field_parser = partial(get_field)

    if opts.get("ptype") == "none":
        conf_parser = cast_none
    elif conf_is_dynamic(conf):
        conf_parser = partial(parse_conf, conf=conf)
    else:
        pre_parsed = parse_conf(None, conf=conf)
        conf_parser = lambda _, **__: pre_parsed

    return ParseFuncs(field_parser, conf_parser)


def get_casters(opts: Opts) -> CastFuncs:
    ftype = opts.get("ftype")
    ptype = opts.get("ptype")
    extract = opts.get("extract")

    if ftype in CAST_SWITCH:
        _field_func = partial(cast_value, _type=CastType(ftype))
        field_func = cast_type(Callable[[ItemArg], ComplexValue], _field_func)
    else:
        if ftype:
            logger.warning(f"Invalid cast {ftype=}. Ignoring.")

        field_func = cast_pass

    if ptype in CAST_SWITCH:
        _caster = partial(cast_value, _type=CastType(ptype))
        caster = cast_type(Callable[[ItemArg], ComplexValue], _caster)
    else:
        if ptype:
            logger.warning(f"Invalid cast {ptype=}. Ignoring.")

        caster = cast_pass

    if ptype == "none":
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

    conf_caster = cast_type(Callable[[ItemArg], AnyModuleConf], _conf_caster)
    return CastFuncs(field_func, extract_caster, conf_caster)
