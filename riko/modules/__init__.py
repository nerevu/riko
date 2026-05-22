# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules
~~~~~~~~~~~~
"""
from copy import copy
from functools import partial, wraps
from itertools import chain
from typing import Any, Iterator, Mapping, NamedTuple, Sequence, overload

from mezmorize.utils import Optional
from riko.types import AsyncOperator, AsyncPipeline, AsyncProcessor, Item, Operator, PipeTuples, Processor, Pipeline, Stream, SyncOperator, SyncPipeline, SyncProcessor

import pygogo as gogo

from riko import Context
from riko.bado import coroutine, return_value
from riko.cast import cast
from riko.utils import multiplex, broadcast, dispatch, StreamState
from riko.types import DispatchFuncs, BroadcastFuncs
from riko.parsers import parse_conf, get_skip, get_field, get_with
from riko.dotdict import DotDict
from meza.fntools import remove_keys, listize, Objectify
from meza.process import merge

logger = gogo.Gogo(__name__, monolog=True).logger

__targets__ = [
    "coroutine",
]

# Operators
__aggregators__ = [
    "count",
    "sum",
    "timeout",
    "aggregate",
    # 'mean',
    # 'min',
    # 'max',
]

__composers__ = [
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
]

# Processors (loopable)
__sources__ = [
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
]

__transformers__ = [
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
]

__all__ = __aggregators__ + __composers__ + __sources__ + __transformers__ + __targets__

SENTINELS = {StreamState.DONE}
CONF_KEYS = {
    "assign",
    "attrs",
    "base",
    "col_names",
    "combine",
    "count",
    "currency",
    "default",
    "delay",
    "delimiter",
    "detag",
    "emit",
    "encoding",
    "end",
    "format",
    "group_key",
    "html5",
    "join_key",
    "length",
    "limit",
    "lower",
    "max_len",
    "max_wait",
    "name",
    "other",
    "other_join_key",
    "param",
    "parse_key",
    "part",
    "path",
    "permit",
    "precision",
    "prompt",
    "skip_rows",
    "sort",
    "start",
    "stop",
    "strict",
    "stringify",
    "sum_key",
    "times",
    "token",
    "type",
    "unique_key",
    "url",
    "wait",
    "xpath",
}


# TODO: figure out why type checker doesn't like Stream
def get_assignment(
    result: Iterator | str | int | Sequence | Mapping,
    skip=False,
    count: Optional[str] = None,
    **kwargs
) -> tuple[bool, Iterator[Item]]:
    items: Iterator[Item] = iter(listize(result))

    if skip:
        one = False
        result = items
    else:
        try:
            first_result = next(items)
        except StopIteration:
            first_result = None

        try:
            second_result = next(items)
        except StopIteration:
            # pipe delivers one result, e.g., strconcat
            if first_result is None:
                items = iter([])
            else:
                items = chain([first_result], items)

            multiple = False
        else:
            # pipe delivers multiple results, e.g., fetchpage/tokenizer
            if first_result is None:
                items = chain([], [second_result], items)
            else:
                items = chain([first_result], [second_result], items)

            multiple = True

        first = bool(count == "first")
        _all = count == "all"
        one = first or not (multiple or _all)

        if one:
            result = iter([]) if first_result is None else iter([first_result])
        else:
            result = items

    return one, result


def assign(item, assignment, one=False, assign=None, **kwargs):
    value = next(assignment) if one else assignment

    if assign and isinstance(value, (str, int, Mapping)):
        merged = merge([item, {assign: value}])
        yield DotDict(merged)
    elif assign:
        merged = merge([item, {assign: list(value)}])
        yield DotDict(merged)
    elif isinstance(value, (Mapping, str, int)):
        yield value
    else:
        yield from value


class Dispatched(NamedTuple):
    item: Item
    parsed: list[Any]


class Module():
    def __init__(
        self, defaults=None, isasync=False, pollable=False, debug=False, **opts
    ):
        self.defaults = defaults or {}
        self.bfuncs = self.dfuncs = self.ftype = None
        self.combined = DotDict(self.defaults)
        self.conf = DotDict(self.defaults)
        self.debug = debug
        self.isasync = isasync
        self.opts = opts or {}
        self.pollable = pollable
        self.types = set([])
        self.updates = {}

    def prepare(
        self,
        module_name: str,
        ftype: Optional[str] = "pass",
        ptype: Optional[str] = "pass",
        emit: Optional[bool] = False,
        assign: Optional[str] = None,
        conf=None,
        **kwargs,
    ):
        defaults = {
            "ftype": ftype,
            "ptype": ptype,
            "objectify": True,
            "emit": emit,
            "assign": assign,
        }
        self.conf.update(conf or {})
        self.combined.update({**self.opts, **defaults, **kwargs})
        self.ftype = self.combined["ftype"]

        for k in CONF_KEYS:
            if k in self.combined:
                self.conf.setdefault(k, self.combined[k])

        extract = self.combined.get("extract")
        pdictize = self.combined.get("listize") if extract else True
        self.combined.setdefault("pdictize", pdictize)
        self.combined.update(self.conf.asdict())

        self.bfuncs = get_broadcast_funcs(self.conf, **self.combined)
        if self.combined["ptype"] != "none":
            self.dfuncs = get_dispatch_funcs(**self.combined)
        else:
            self.dfuncs = None


class processor(Module):
    def __init__(
        self, *args, **kwargs):
        """Creates a sync/async pipe that processes individual items. These
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

            pdictize (bool): Convert `conf` or an `extract` to a
                riko.dotdict.DotDict instance (default: True unless
                `listize` is False and `extract` is True)

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
                `ftype` is 'none', pipe name otherwise)

            emit (bool): Return the stream as is and don't assign it to an item
                attribute (default: True if `ftype` is set to 'none', False
                otherwise).

            skip_if (func): A function that takes the `item` and should return
                True if processing should be skipped, or False otherwise. If
                processing is skipped, the resulting stream will be the original
                input `item`.

        Examples:
            >>> from riko.bado import react, util, _issync
            >>> from riko.bado.mock import FakeReactor
            >>>
            >>> @processor()
            ... def pipe(item, objconf, skip=False, **kwargs):
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
            ... def async_pipe(item, objconf, skip=False, **kwargs):
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
            >>> response = {'content': 'say "hello world" three times!'}
            >>> next(pipe(item, **kwargs)) == response
            True
            >>>
            >>> def run(reactor):
            ...     callback = lambda x: print(next(x) == response)
            ...     d = async_pipe(item, **kwargs)
            ...     return d.addCallbacks(callback, logger.error)
            ...
            >>> if _issync:
            ...     True
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            True
        """
        super().__init__(*args, **kwargs)

    @overload
    def __call__(self, pipe: SyncProcessor) -> SyncPipeline:
        pass
    @overload
    def __call__(self, pipe: AsyncProcessor) -> AsyncPipeline:
        pass
    def __call__(self, pipe: Processor) -> Pipeline:
        """Creates a sync/async pipe that processes individual items

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
            ...     'pdictize': False, 'emit': True, 'field': 'content',
            ...     'objectify': False}
            ...
            >>> @processor(**kwargs)
            ... def pipe(content, times, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         stream = {kwargs['assign']: value}
            ...
            ...     return stream
            ...
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> @processor(isasync=True, **kwargs)
            ... def async_pipe(content, times, skip=False, **kwargs):
            ...     if skip:
            ...         stream = kwargs['stream']
            ...     else:
            ...         value = 'say "%s" %s times!' % (content, times[0])
            ...         stream = {kwargs['assign']: value}
            ...
            ...     return stream
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
            ...     True
            ... else:
            ...     try:
            ...         react(run, _reactor=FakeReactor())
            ...     except SystemExit:
            ...         pass
            Attention! Running fake reactor. Some deferreds may not work as intended.
            {'content': 'say "hello world" three times!'}
        """
        @wraps(pipe)
        def wrapper(item: Optional[Item | Iterator[Item]] =None, **kwargs):
            module_name = wrapper.__module__.split(".")[-1]
            self.prepare(module_name, **kwargs)
            is_source = self.ftype == "none"
            _assign = None if is_source else module_name
            self.prepare(module_name, emit=is_source, assign=_assign, **kwargs)

            if isinstance(item, Iterator):
                items = map(DotDict, item)
            elif item:
                items = iter([DotDict(item)])
            else:
                items = iter([DotDict()])

            for _INPUT in items:
                if skip := get_skip(_INPUT, **self.combined):
                    self.dfuncs = None

                if self.bfuncs:
                    orig_item, parsed = _dispatch(_INPUT, self.bfuncs, dfuncs=self.dfuncs)
                else:
                    print(f"{module_name} bfuncs missing!")
                    orig_item, parsed = {}, []

                kwargs.update({"skip": skip, "stream": orig_item})

                if self.isasync:
                    _stream = yield pipe(*parsed, **kwargs)
                else:
                    _stream = pipe(*parsed, **kwargs)

                if callable(_stream):
                    _stream = _stream()

                one, assignment = get_assignment(_stream, **self.conf)

                if skip or self.conf.get("emit"):
                    stream = assignment
                else:
                    stream = assign(_INPUT, assignment, one=one, **self.conf)

                if self.isasync:
                    return_value(stream)
                else:
                    yield from stream

        is_source = self.ftype == "none"
        wrapper.__dict__["name"] = wrapper.__module__.split(".")[-1]
        wrapper.__dict__["type"] = "processor"
        wrapper.__dict__["sub_type"] = "source" if is_source else "transformer"
        wrapper.__dict__["pollable"] = self.pollable
        return coroutine(wrapper) if self.isasync else wrapper


class operator(Module):
    def __init__(self, *args, **kwargs):
        """Creates a sync/async pipe that processes an entire stream of items

        Args:
            defaults (dict): Default `conf` values.
            isasync (bool): Wraps an async pipe (default: False)
            opts (dict): The keyword arguments passed to the wrapper

        Kwargs:
            conf (dict): The pipe configuration
            extract (str): The key with which to get values from `conf`. If set,
                the wrapped pipe will receive these value instead of `conf`
                (default: None).

            listize (bool): Ensure that the value returned from an `extract` is
                list-like (default: False)

            pdictize (bool): Convert `conf` or an `extract` to a
                riko.dotdict.DotDict instance (default: True if either
                `extract` is False or both `listize` and `extract` are True)

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

            assign (str): Attribute to assign stream (default: the pipe name)
            embed (dict): Must have key "type". May have key "conf",
            with (str):

            emit (bool): return the stream as is and don't assign it to an item
                attribute (default: True).

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
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
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
            ...     True
            ...     True
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
    def __call__(self, pipe: SyncOperator) -> SyncPipeline:
        pass
    @overload
    def __call__(self, pipe: AsyncOperator) -> AsyncPipeline:
        pass
    def __call__(self, pipe: Operator) -> Pipeline:
        """Creates a wrapper that allows a sync/async pipe to processes a
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
            ...     'pdictize': False, 'emit': True, 'field': 'content',
            ...     'objectify': False}
            ...
            >>> wrapper = operator(**opts)
            >>>
            >>> def pipe1(stream, objconf, tuples, **kwargs):
            ...     for content, times in tuples:
            ...         value = 'say "{content}" {0} times!'.format(*times, **content)
            ...         yield {kwargs['assign']: value}
            ...
            >>> def pipe2(stream, objconf, tuples, **kwargs):
            ...     word_cnt = _sum(len(item['content'].split()) for item in stream)
            ...     return {kwargs['assign']: word_cnt}
            ...
            >>> wrapped_pipe1 = wrapper(pipe1)
            >>> wrapped_pipe2 = wrapper(pipe2)
            >>> items = [{'content': 'hello world'}, {'content': 'bye world'}]
            >>> kwargs = {'conf':  {'times': 'three'}, 'assign': 'content'}
            >>>
            >>> next(wrapped_pipe1(items, **kwargs))
            {'content': 'say "hello world" three times!'}
            >>> next(wrapped_pipe2(items, **kwargs))
            {'content': 4}
            >>> async_wrapper = operator(isasync=True, **opts)
            >>>
            >>> # async pipes don't have to return a deferred,
            >>> # they work fine either way
            >>> def async_pipe1(stream, objconf, tuples, **kwargs):
            ...     for content, times in tuples:
            ...         value = 'say "{content}" {0} times!'.format(*times, **content)
            ...         yield {kwargs['assign']: value}
            ...
            >>> # this is an admittedly contrived example to show how you would
            >>> # call an async function
            >>> @coroutine
            ... def async_pipe2(stream, objconf, tuples, **kwargs):
            ...     words = (len(item['content'].split()) for item in stream)
            ...     word_cnt = yield maybeDeferred(_sum, words)
            ...     return_value({kwargs['assign']: word_cnt})
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
            Attention! Running fake reactor. Some deferreds may not work as intended.
            {'content': 'say "hello world" three times!'}
            {'content': 4}
        """

        @wraps(pipe)
        def wrapper(items=None, **kwargs):
            items = items or iter([])
            _INPUT = map(DotDict, items)
            module_name = wrapper.__module__.split(".")[-1]
            wrapper.__dict__["name"] = module_name
            context = kwargs.pop("context", Context())
            self.prepare(module_name, emit=True, assign=module_name, **kwargs)

            # `assign` is stored in `conf`, which means operators can't access both it
            # (via `tuples`) and `stream` at the same time. Copying it to kwargs resolves
            # this issue.
            kwargs["assign"] = self.combined.get("assign")

            # - operators can't skip items
            # - purposely setting both variables to maps of the same iterable
            #   since only one is intended to be used at any given time
            # - `tuples` is an iterator of tuples of the item and second objconf
            if self.bfuncs:
                dispatcher = partial(_dispatch, bfuncs=self.bfuncs, dfuncs=self.dfuncs)
                dispatches = map(dispatcher, _INPUT)
                tuples: PipeTuples = ((d.item, d.parsed[1]) for d in dispatches)
                orig_stream = (d.item for d in dispatches)
                d = dispatcher(DotDict())
                objconf = d.parsed[1]
            else:
                print(f"{module_name} bfuncs missing!")
                tuples, orig_stream = map(iter, ([], _INPUT))
                objconf = Objectify({})

            if context.submodule:
                context.inputs = objconf

            if embedded_pipe := kwargs.pop("embed", None):
                # Prepare submodule to take parameters from the loop instead the user
                embedded_kwargs = self.conf.pop("embed").asdict()
                embed_context = copy(context)
                embed_context.submodule = True
                _stream = embedded_pipe(items, context=embed_context, **embedded_kwargs)
            else:
                args = (orig_stream, objconf, tuples)

                if self.isasync:
                    _stream: Stream = yield pipe(*args, **kwargs)
                else:
                    _stream: Stream = pipe(*args, **kwargs)

                if callable(_stream):
                    _stream = _stream()

                sub_type = "aggregator" if hasattr(_stream, "keys") else "composer"
                wrapper.__dict__["sub_type"] = sub_type

            # operators can only assign one value per item and can't skip items
            # print(f"{module_name} {combined=}")
            _conf = self.conf.asdict()
            _, assignment = get_assignment(_stream, **_conf)

            if _conf.get("emit"):
                stream = assignment
            else:
                singles = (iter([v]) for v in assignment)
                assigned = (assign({}, s, one=True, **_conf) for s in singles)
                stream = multiplex(assigned)

            if self.isasync:
                return_value(stream)
            else:
                yield from stream

        wrapper.__dict__["type"] = "operator"
        return coroutine(wrapper) if self.isasync else wrapper


def _dispatch(
    item: Item,
    bfuncs: BroadcastFuncs,
    dfuncs: Optional[DispatchFuncs] = None
) -> Dispatched:
    split = broadcast(item, *bfuncs)
    parsed = dispatch(split, *dfuncs) if dfuncs else split
    return Dispatched(item, parsed)


def get_broadcast_funcs(conf=None, **kwargs) -> BroadcastFuncs:
    kw = Objectify(kwargs)
    conf = Objectify(conf or {})

    if kw.extract:
        try:
            pieces = next(v for k, v in conf.items() if k.lower() == kw.extract)
        except StopIteration:
            raise KeyError(f"extract {kw.extract=} not found in {conf=}")
    else:
        pieces = conf

    if kw.listize:
        listed: list[Any] = listize(pieces)
        piece_defs = map(DotDict, listed) if kw.pdictize else listed
        parser = partial(parse_conf, conf=conf, **kwargs)
        pfuncs = [partial(parser, conf=piece_def) for piece_def in piece_defs]
        conf_func = lambda item: broadcast(item, *pfuncs)
    elif kw.ptype != "none":
        _conf = DotDict(pieces) if kw.pdictize and pieces else pieces
        conf_func = partial(parse_conf, conf=_conf, **kwargs)
    else:
        conf_func = lambda _: None

    if kw.ftype == "none":
        field_func = lambda _: None
    elif kw.ftype == "with":
        field_func = partial(get_with, **kwargs)
    else:
        field_func = partial(get_field, **kwargs)

    return BroadcastFuncs(field_func, conf_func)


def get_dispatch_funcs(**kwargs) -> DispatchFuncs:
    # ftype:
    #     'word': partial(df.maybeDeferred, get_word) if async else get_word,
    #     'num': partial(df.maybeDeferred, get_num) if async else get_num,
    #     'pass': passthrough,
    #     None: lambda _: tu.asyncNone if async else utils.passnone,
    listize = kwargs.get("listize")
    pfunc = partial(cast, _type=kwargs["ptype"])
    objectify = partial(Objectify, func=pfunc)
    field_dispatch = partial(cast, _type=kwargs["ftype"])

    # TODO: add check to only objectify if extracted value is a dict
    if listize and kwargs["objectify"] and kwargs["ptype"] != "none":
        conf_dispatch = lambda confs: [objectify(conf) for conf in confs]
    elif kwargs["objectify"] and kwargs["ptype"] != "none":
        conf_dispatch = objectify
    else:
        conf_dispatch = pfunc

    return DispatchFuncs(field_dispatch, conf_dispatch)
