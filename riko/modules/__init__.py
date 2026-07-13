# vim: sw=4:ts=4:expandtab
"""
riko.modules
~~~~~~~~~~~~
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from copy import copy
from functools import partial, wraps
from itertools import chain
from time import struct_time
from typing import Optional, TypeVar, overload
from typing import cast as cast_type

import pygogo as gogo
from meza.process import merge

from riko import Context, Objconf, Objectify, listize, objectify
from riko.bado import coroutine, return_value
from riko.cast import CAST_SWITCH, CastType, cast_none, cast_pass
from riko.cast import cast as cast_value
from riko.dotdict import DotDict
from riko.parsers import get_field, get_skip, parse_conf
from riko.types.general import (
    AsyncOperatorParser,
    AsyncOperatorWrapper,
    AsyncProcessorParser,
    AsyncProcessorWrapper,
    BasicArg,
    BasicDict,
    BasicMapping,
    Casted,
    CastFuncs,
    ComplexArg,
    ComplexValue,
    Defaults,
    Dispatched,
    ItemArg,
    Items,
    ItemsResult,
    OperatorItems,
    OperatorParser,
    OperatorWrapper,
    ParsedConf,
    ParseFuncs,
    PipeTuples,
    ProcessorItems,
    ProcessorParser,
    ProcessorWrapper,
    SyncOperatorParser,
    SyncOperatorWrapper,
    SyncProcessorParser,
    SyncProcessorWrapper,
)
from riko.utils import StreamState, broadcast, dispatch

logger = gogo.Gogo(__name__, monolog=True).logger

__targets__ = ("coroutine",)

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

# __all__ = __aggregators__ + __composers__ + __sources__ + __transformers__ + __targets__

SENTINELS = {StreamState.DONE}

T = TypeVar("T", bound=ComplexArg)


def dictize(data: Mapping | T) -> DotDict | T:
    if isinstance(data, Objectify):
        result = data
    elif isinstance(data, Mapping):
        result = DotDict(data)
    else:
        result = data

    return result


# TODO: figure out why type checker doesn't like Stream
def get_assignment(
    items: ProcessorItems | OperatorItems, skip=False, count: str | None = None, **_
) -> tuple[bool, Iterator[ComplexArg]]:
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
    assignment: ItemsResult,
    one=False,
    assign: str | None = None,
    **kwargs,
) -> Iterator[ComplexArg]:
    value = next(assignment, None) if one else assignment

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


class Module:
    def __init__(
        self,
        defaults: Defaults | None = None,
        isasync=False,
        pollable=False,
        debug=False,
        ftype: str | None = "pass",
        ptype: str | None = "pass",
        **opts,
    ):
        # Only called once on pipe import
        self._defaults = cast_type(dict[str, str | bool | BasicArg], defaults or {})
        self.opts = {"ftype": ftype, "ptype": ptype, **opts}
        self.parsers = self.casters = None
        self.combined = DotDict()
        self.conf = None
        self.debug = debug
        self.isasync = isasync
        self.pollable = pollable
        self.types = set([])
        self.assign = None
        self.emit = None
        self.name = None
        self.is_source = False
        self.sub_type = None

    def prepare(
        self,
        module_name: str,
        conf: BasicMapping | None = None,
        assign: str | None = None,
        emit: bool | None = None,
        **kwargs,
    ):
        # Called on every pipe execution
        if emit is None:
            def_emit = self.opts.get("emit")
        else:
            def_emit = emit

        if assign is None:
            def_assign = self.opts.get("assign")
        else:
            def_assign = assign

        self.name = module_name
        self.combined = DotDict({**self._defaults, **self.opts})
        self.combined.setdefault("objectify", self.combined["ptype"] != "none")
        self.conf = DotDict({**self._defaults, **(conf or {})})

        if "operator" in str(self):
            self.emit = True if def_emit is None else def_emit
            self.assign = None if self.emit else def_assign or module_name
        elif "processor" in str(self):
            self.combined["ftype"] = self.opts["ftype"]
            self.is_source = self.opts["ftype"] == "none"
            self.emit = self.is_source if def_emit is None else def_emit
            assignment = "content" if self.is_source else module_name
            self.assign = None if self.emit else def_assign or assignment
            self.sub_type = "source" if self.is_source else "transformer"
        else:
            print(f"Unknown module {self}.")

        _conf = self.conf.asdict()
        self.combined.update(kwargs)
        self.combined["emit"] = self.emit
        self.combined["assign"] = self.assign

        _combined = self.combined.asdict()
        self.parsers = get_parsers(_conf, **_combined)

        if self.combined["ptype"] == "none":
            self.casters = None
        else:
            self.casters = get_casters(**_combined)


class processor(Module):
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
            ... def pipe(item, extraction, objconf, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         content = item['content']
            ...         stream = 'say "%s" %s times!' % (content, objconf.times)
            ...
            ...     return stream
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @processor(isasync=True)
            ... @coroutine
            ... def async_pipe(item, extraction, objconf, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         content = yield util.async_return(item['content'])
            ...         stream = 'say "%s" %s times!' % (content, objconf.times)
            ...
            ...     return_value(stream)
            ...
            >>> item = {'content': 'hello world'}
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> next(pipe(item, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(next(x))
            ...     d = async_pipe(item, **kwargs)
            ...     return d.addCallbacks(callback, logger.error)
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

    @overload
    def __call__(self, pipe: AsyncProcessorParser) -> AsyncProcessorWrapper: ...
    @overload
    def __call__(self, pipe: SyncProcessorParser) -> SyncProcessorWrapper: ...
    def __call__(self, pipe: ProcessorParser) -> ProcessorWrapper:
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
            ... def pipe(content, times, objconf, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         stream = 'say "%s" %s times!' % (content, times[0])
            ...
            ...     return stream
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @processor(isasync=True, **kwargs)
            ... def async_pipe(content, times, objconf, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         stream = 'say "%s" %s times!' % (content, times[0])
            ...
            ...     return stream
            ...
            >>> item = {'content': 'hello world'}
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>> next(pipe(item, **kwargs))
            'say "hello world" three times!'
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(next(x))
            ...     d = async_pipe(item, **kwargs)
            ...     return d.addCallbacks(callback, logger.error)
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

        @wraps(pipe)
        def wrapper(
            item: ItemArg | None = None, conf: BasicMapping | None = None, **kwargs
        ) -> ItemsResult:
            module_name = wrapper.__module__.split(".")[-1]

            if isinstance(item, (Mapping, str)):
                _INPUT = dictize(item)
            elif isinstance(item, Iterator):
                items = list(item)

                if (item_count := len(items)) > 1:
                    msg = f"{module_name} received an Iterator of {item_count} items. "
                    msg += "Did you forget to use a loop? Processing only the first "
                    msg += "item."
                    logger.error(msg)

                _INPUT = dictize(items[0])
            else:
                _INPUT = DotDict()

            self.prepare(module_name, conf=conf, **kwargs)
            _emit, _assign = self.emit, self.assign
            _conf = cast_type(ParsedConf, self.conf.asdict())
            skip = get_skip(_INPUT, **self.combined)

            args = (_INPUT, self.parsers, self.casters)
            combined = self.combined.asdict()
            defaults = cast_type(Defaults, combined.pop("defaults", None))
            orig_item, casted = _dispatch(*args, defaults=defaults, **combined)

            kwargs.update({"skip": skip, "stream": orig_item, "assign": _assign})

            if self.isasync:
                ___stream = cast_type(AsyncProcessorParser, pipe)(*casted, **kwargs)
                __stream = yield ___stream  # pyright: ignore[reportReturnType]
                _stream = cast_type(ItemArg, __stream)
            else:
                _stream = cast_type(SyncProcessorParser, pipe)(*casted, **kwargs)

            one, assignment = get_assignment(_stream, skip=skip, **_conf)

            if isinstance(_INPUT, (str, int)) or skip or _emit:
                stream = assignment
            else:
                stream = gen_assignments(
                    _INPUT, assignment, one=one, assign=_assign, **_conf
                )

            if self.isasync:
                return_value(stream)
            else:
                yield from stream

        wrapper.type = "processor"
        wrapper.name = pipe.__module__.split(".")[-1]
        sub_type = "source" if self.opts["ftype"] == "none" else "transformer"
        wrapper.sub_type = sub_type
        wrapper.pollable = self.pollable

        result = coroutine(wrapper) if self.isasync else wrapper  # pyright: ignore[reportArgumentType]
        return cast_type(SyncProcessorWrapper, result)


class operator(Module):
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
            >>> from builtins import sum as _sum, len
            >>> from riko.bado import react, util, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> # emit is True by default
            >>> # and operators can't skip items, so the pipe is passed an
            >>> # item dependent version of objconf as the 3rd arg
            >>> @operator(emit=False)
            ... def pipe1(stream, objconf, tuples, **kwargs):
            ...     for item, objconf in tuples:
            ...         s = 'say "%s" %s times!'
            ...         yield s % (item['content'], objconf.times)
            ...
            >>> @operator(emit=False)
            ... def pipe2(stream, objconf, tuples, **kwargs):
            ...     return _sum(len(item['content'].split()) for item in stream)
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @operator(isasync=True, emit=False)
            ... @coroutine
            ... def async_pipe1(stream, objconf, tuples, **kwargs):
            ...     for item, objconf in tuples:
            ...         content = yield util.async_return(item['content'])
            ...         value = 'say "%s" %s times!' % (content, objconf.times)
            ...         return_value(value)
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @operator(isasync=True, emit=False)
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     return _sum(len(item['content'].split()) for item in stream)
            ...
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> conf = {'times': 'three'}
            >>> kwargs = {'conf': conf, 'assign': 'content', 'emit': False}
            >>> next(pipe1(items, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>> next(pipe2(items, **kwargs))
            {'content': 4}
            >>>
            >>> @coroutine
            ... def run(reactor):
            ...     r1 = yield async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = yield async_pipe2(items, **kwargs)
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

    @overload
    def __call__(self, pipe: AsyncOperatorParser) -> AsyncOperatorWrapper: ...

    @overload
    def __call__(self, pipe: SyncOperatorParser) -> SyncOperatorWrapper: ...

    def __call__(self, pipe: OperatorParser) -> OperatorWrapper:
        """
        Creates a wrapper that allows a sync/async pipe to processes a
        stream of items

        Args:
            pipe (func): A function of 3 args (stream, objconf, tuples)
                and a `**kwargs`. TODO: document args & kwargs.

        Returns:
            func: A function of 1 arg (items) and a `**kwargs`.

        Examples:
            >>> from builtins import sum as _sum, len
            >>> from riko.bado import react, _issync
            >>> from riko.bado.mock import FakeReactor
            >>> from riko.bado.util import maybeDeferred
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
            ...     return _sum(len(item['content'].split()) for item in stream)
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
            >>> @coroutine
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     words = (len(item['content'].split()) for item in stream)
            ...     word_cnt = yield maybeDeferred(_sum, words)
            ...     return_value(word_cnt)
            ...
            >>> wrapped_async_pipe1 = async_wrapper(async_pipe1)
            >>> wrapped_async_pipe2 = async_wrapper(async_pipe2)
            >>>
            >>> @coroutine
            ... def run(reactor):
            ...     r1 = yield wrapped_async_pipe1(items, **kwargs)
            ...     print(next(r1))
            ...     r2 = yield wrapped_async_pipe2(items, **kwargs)
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

        @wraps(pipe)
        def wrapper(
            items: Items | None = None,
            conf: BasicMapping | None = None,
            embed: ProcessorWrapper | None = None,
            **kwargs,
        ) -> ItemsResult:
            _INPUT = map(dictize, iter(items or []))
            module_name = wrapper.__module__.split(".")[-1]
            # print(f"\n## Wrapping operator {module_name} - {id(wrapper)} ##\n")
            # print(f"{module_name} {items=}")
            # print(f"{module_name} {_INPUT=}")
            self.prepare(module_name, conf=conf, **kwargs)
            _emit, _assign = self.emit, self.assign
            embedded_kwargs = cast_type(BasicDict, self.conf.pop("embed", None))
            _conf = cast_type(ParsedConf, self.conf.asdict())
            # print(f"{module_name} {kwargs=}")
            context = kwargs.pop("context", Context())

            # - operators can't skip items
            # - purposely setting both tuples and orig_stream to maps of the same
            #   iterable since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and second objconf
            combined = self.combined.asdict()
            defaults = cast_type(Defaults, combined.pop("defaults", None))
            _dispatcher = partial(
                _dispatch, parsers=self.parsers, casters=self.casters, defaults=defaults
            )
            dispatcher = cast_type(Callable[[ItemArg], Dispatched], _dispatcher)

            # Parses conf that can vary per item. Can't handle terminal input.
            allowed = {"extract", "listize", "defaults", "field"}
            dkwargs = {k: v for k, v in combined.items() if k in allowed}
            dispatches = (dispatcher(item, **dkwargs) for item in _INPUT)
            tuples: PipeTuples = (
                (d.item, cast_type(Objconf, d.casted.conf)) for d in dispatches
            )
            orig_stream = (d.item for d in dispatches)

            # Parses conf that doesn't vary per item and may contain terminal input
            casted = dispatcher(DotDict(), **combined).casted

            if context.submodule:
                context.inputs = kwargs.get("inputs")

            if embed and embed.name == "input":
                logger.error("Embedding input pipes is not currently supported.")
                _stream = _INPUT
            elif embed and embed.type == "processor":
                embed_context = copy(context)
                embed_context.submodule = True
                embedded_kwargs["context"] = embed_context
                embedder = partial(embed, **embedded_kwargs)
                # print(f"Embedding {embed.name} with {embedded_kwargs=}")
                stream_map = map(embedder, _INPUT)

                if self.isasync:
                    logger.error("Embedding async pipes is not currently supported.")
                    _stream = _INPUT
                else:
                    sync_stream_map = cast_type(Iterable[Items], stream_map)
                    _stream = chain.from_iterable(sync_stream_map)
            elif embed:
                msg = "Only processor pipes can be embedded."
                msg = "Got {type} pipe {name}.".format(**embed.__dict__)
                logger.error(msg)
                _stream = _INPUT
            elif module_name == "loop":
                logger.error("No embedded pipe provided!")
                _stream = _INPUT
            else:
                args = (orig_stream, casted.extraction, tuples)

                if self.isasync:
                    ___stream = cast_type(AsyncOperatorParser, pipe)(*args, **kwargs)  # pyright: ignore[reportArgumentType]
                    __stream = yield ___stream  # pyright: ignore[reportReturnType]
                    _stream = cast_type(Items, __stream)
                else:
                    _stream = cast_type(SyncOperatorParser, pipe)(*args, **kwargs)

                # if callable(_stream):
                #     _stream = _stream()

            self.sub_type = "aggregator" if isinstance(_stream, Mapping) else "composer"
            wrapper.sub_type = self.sub_type
            # operators can only assign one value per item and can't skip items
            # print(f"{module_name} {combined=}")
            _, assignment = get_assignment(_stream, skip=False, **_conf)

            if _emit:
                stream = assignment
            else:
                singles = (iter([v]) for v in assignment)
                assigned = (
                    gen_assignments({}, s, one=True, assign=_assign, **_conf)
                    for s in singles
                )
                stream = chain.from_iterable(assigned)

            if self.isasync:
                return_value(stream)
            else:
                yield from stream

            # print(f"\n## Ended operator {module_name} - {id(wrapper)} ##\n")
            #

        # wrapper.__dict__["type"] = "operator"
        wrapper.type = "operator"
        wrapper.name = pipe.__module__.split(".")[-1]
        wrapper.sub_type = None
        wrapper.pollable = self.pollable

        # https://github.com/python/mypy/issues/15737
        result = coroutine(wrapper) if self.isasync else wrapper  # pyright: ignore[reportArgumentType]
        return cast_type(SyncOperatorWrapper, result)


def _dispatch(
    item: ItemArg,
    parsers: ParseFuncs | None = None,
    casters: CastFuncs | None = None,
    defaults: Defaults | None = None,
    **kwargs,
) -> Dispatched:
    _defaults: Defaults = defaults or {}
    kw = Objectify(kwargs)

    if parsers:
        parsed_field, parsed_conf = broadcast(item, *parsers, **kwargs)
    else:
        parsed_field, parsed_conf = item, kw.conf

    if isinstance(parsed_conf, Mapping):
        merged_conf = {**_defaults, **parsed_conf}
    else:
        merged_conf = {**_defaults}

    if kw.extract:
        try:
            pieces = next(v for k, v in merged_conf.items() if k.lower() == kw.extract)
        except StopIteration:
            logger.error(f"{kw.extract=} not found in conf {merged_conf}")
            pieces = None
        else:
            pieces = cast_type(BasicArg, pieces)

        pieces_or_conf = listize(pieces) if kw.listize else pieces
    else:
        pieces_or_conf = merged_conf

    parsed = (parsed_field, pieces_or_conf, merged_conf)
    casted = dispatch(parsed, *casters) if casters else parsed
    return Dispatched(item, Casted(casted[0], casted[1], casted[2]))


def get_parsers(conf=None, **kwargs) -> ParseFuncs:
    conf = conf or {}
    kw = Objectify(kwargs)

    if kw.ftype == "none":
        field_parser = cast_none
    else:
        field_parser = partial(get_field)

    if kw.ptype == "none":
        conf_parser = cast_none
    else:
        conf_parser = partial(parse_conf, conf=conf)

    return ParseFuncs(field_parser, conf_parser)


def get_casters(**kwargs) -> CastFuncs:
    kw = Objectify(kwargs)

    if kw.ftype in CAST_SWITCH:
        _field_func = partial(cast_value, _type=CastType(kw.ftype))
        field_func = cast_type(Callable[[ComplexArg], ComplexValue], _field_func)
    else:
        if kw.ftype:
            print(f"Invalid cast {kw.ftype=}. Ignoring.")

        field_func = cast_pass

    if kw.ptype in CAST_SWITCH:
        _caster = partial(cast_value, _type=CastType(kw.ptype))
        caster = cast_type(Callable[[ComplexArg], ComplexValue], _caster)
    else:
        if kw.ptype:
            print(f"Invalid cast {kw.ptype=}. Ignoring.")

        caster = cast_pass

    if kw.ptype == "none":
        extract_caster = conf_caster = cast_none
    elif kw.listize and kw.objectify:
        extract_caster = lambda pieces: [objectify(piece, caster) for piece in pieces]
        conf_caster = objectify
    elif kw.objectify:
        extract_caster = partial(objectify, func=caster)
        conf_caster = objectify if kw.extract else partial(objectify, func=caster)
    else:
        extract_caster = caster
        conf_caster = cast_pass

    return CastFuncs(field_func, extract_caster, conf_caster)
