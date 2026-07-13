# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.collections
~~~~~~~~~~~~~~~~
Provides functions for creating (a)synchronous riko flows and streams

Examples:
    sync usage::

        >>> from riko.collections import SyncPipe
        >>> from riko import get_path
        >>>
        >>> fconf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'field': 'title'}}
        >>>
        >>> (SyncPipe('fetchdata', conf=fconf)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ...     .list
        ... )
        [169]
        >>> (SyncPipe('fetchdata', conf=fconf)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count(emit=False)
        ...     .list
        ... )
        [{'count': 169}]
        >>> (SyncPipe('fetchdata', conf=fconf, parallel=True)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ...     .list
        ... )
        [169]
        >>> (SyncPipe('fetchdata', conf=fconf, parallel=True, threads=False)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ...     .list
        ... )
        [169]
        >>> fconf['type'] = 'fetchdata'
        >>> sources = [{'url': get_path('feed.xml')}, fconf]
        >>> stream = SyncCollection(sources)
        >>> next(stream)['title']
        'Donations'
        >>> len(list(stream))
        55
        >>> len(SyncCollection(sources).list)
        56
        >>> len(SyncCollection(sources, parallel=True).list)
        56

    async usage::

        >>> from riko import get_path
        >>> from riko.bado import coroutine, react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.collections import AsyncPipe, AsyncCollection
        >>>
        >>> fconf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'field': 'title'}}
        >>>
        >>> @coroutine
        ... def run(reactor):
        ...     d = yield (AsyncPipe('fetchdata', conf=fconf)
        ...         .sort(conf=sort_conf)
        ...         .tokenizer(conf=str_conf, **str_kwargs)
        ...         .count()
        ...         .alist
        ...     )
        ...
        ...     print(d)
        ...
        >>> if _issync:
        ...     [169]
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [169]
        >>> @coroutine
        ... def run(reactor):
        ...     fconf['type'] = 'fetchdata'
        ...     sources = [{'url': get_path('feed.xml')}, fconf]
        ...     d = yield AsyncCollection(sources).alist
        ...     print(d[0]['title'])
        ...     print(len(d))
        ...
        >>> if _issync:
        ...     Donations
        ...     56
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        Donations
        56
"""
from functools import partial
from io import StringIO
from itertools import repeat, chain
from importlib import import_module
from multiprocessing import Pool as CPUPool, cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from operator import length_hint
from typing import TYPE_CHECKING, Callable, Generator, Iterable, Iterator, Literal, Mapping, Optional, Sequence, TypeAlias, Union, cast, overload

from twisted.internet.defer import Deferred

from riko import listize
import pygogo as gogo

from riko.types.modules import ConfArg

try:
    from csv2ofx.mappings.default import mapping
    from csv2ofx.ofx import OFX
    from csv2ofx.qif import QIF
    from csv2ofx.utils import gen_data
except ModuleNotFoundError:
    mapping = OFX = QIF = gen_data = None

from riko import Context
from riko.types.general import BasicDict, BasicMapping, BasicValue, ComplexArg, ConversionFunc, ItemArg, Items, SyncPipeResult, SyncPipeline, SyncProcessorParser
from riko.utils import send, StreamState
from riko.bado import coroutine, return_value
from riko.bado import itertools as ait
from riko.bado.util import async_return
from meza import convert as cv, io
from meza.process import merge

if TYPE_CHECKING:
    from multiprocessing.pool import Pool as CPUPoolType
    from multiprocessing.dummy import Pool as ThreadPoolType

AnyPool: TypeAlias = Union["ThreadPoolType", "CPUPoolType"]

logger = gogo.Gogo(__name__, monolog=True).logger


def records2ofx(items, **_) -> Iterable[str]:
    ofx = OFX(mapping)
    groups = ofx.gen_groups(items)
    trxns = ofx.gen_trxns(groups)
    cleaned_trxns = ofx.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain([ofx.header(), ofx.gen_body(data), ofx.footer()])


def records2qif(items, **_) -> Iterable[str]:
    qif = QIF(mapping)
    groups = qif.gen_groups(items)
    trxns = qif.gen_trxns(groups)
    cleaned_trxns = qif.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain([qif.header(), qif.gen_body(data), qif.footer()])


CONVERSION_FUNCS: dict[str, ConversionFunc] = {
    # "array": cv.records2array,
    "csv": cv.records2csv,
    # "dataframe": cv.records2df,
    "geojson": cv.records2geojson,
    # 'ical': cv.records2ical,
    "json": cv.records2json,
    # 'kml': cv.records2kml,
    "list": lambda items, **kw: list(items),
    "ofx": cast(ConversionFunc, records2ofx),
    "qif": cast(ConversionFunc, records2qif),
    "tuple": lambda items, **kw: tuple(items),
}


@overload
def export(items) -> list[ItemArg]:
    ...
@overload  # noqa: E302
def export(items, **kwargs) -> list[ItemArg]:
    ...
@overload  # noqa: E301, E302
def export(items, _type: Literal["list"], **kwargs) -> list[ItemArg]:
    ...
@overload  # noqa: E301, E302
def export(items, _type: Literal["tuple"], **kwargs) -> tuple[ItemArg]:
    ...
@overload  # noqa: E301, E302
def export(items, _type: Literal["csv", "json", "geojson"], f: str, **kwargs) -> int:
    ...
@overload  # noqa: E301, E302
def export(items, _type: Literal["csv", "json", "geojson"], f: None = ..., **kwargs) -> StringIO:
    ...
@overload  # noqa: E301, E302
def export(items, _type: str = ..., **kwargs) -> Optional[StringIO | Iterable[ItemArg]]:
    ...
def export(  # noqa: E302
    items: Items,
    _type: str = "list",
    f: Optional[str] = None,
    **kwargs
) -> Optional[int | StringIO | Iterable[ItemArg]]:
    result = None

    if converter := CONVERSION_FUNCS.get(_type):
        _result = converter(items, **kwargs)

        if f:
            result = cast(int, io.write(f, _result, **kwargs))
        else:
            result = _result
    else:
        logger.error(f"Invalid type, {_type}. You must supply one of {CONVERSION_FUNCS}.")

    return result


class PyPipe(object):
    """A riko module fetching object

    Kwargs:

    verbose = debug printing during compilation and running
    describe_input = return pipe input requirements
    describe_dependencies = return a list of sub-pipelines used
    test = takes input values from default (skips the console prompt)
    inputs = a dictionary of values that overrides the defaults
        e.g. {'name one': 'test value1'}
    """

    def __init__(
        self,
        name: Optional[str] = None,
        parallel=False,
        inputs: Optional[BasicDict] = None,
        context: Optional[Context] = None,
        **kwargs: BasicValue | BasicMapping | Context
    ):
        self.name = name
        self.parallel = parallel
        self.inputs = inputs or {}
        self.verbose = kwargs.get("verbose")
        self.test = kwargs.get("test")
        self.context = context or Context(**kwargs)
        self.describe_input = self.context.describe_input
        self.describe_dependencies = self.context.describe_dependencies
        self.kwargs = kwargs
        self.kwargs.update({"inputs": self.inputs, "context": self.context})

    def __call__(self, **kwargs: BasicValue | BasicMapping):
        self.kwargs.update(kwargs)
        return self


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""

    def __init__(
        self,
        name: Optional[str] = None,
        source: Optional[Items] = None,
        workers: Optional[int] = None,
        chunksize: Optional[int] = None,
        threads: Optional[bool] = True,
        reuse_pool: Optional[bool] = True,
        pool: Optional[AnyPool] = None,
        ordered: Optional[bool] = False,
        **kwargs: BasicValue | BasicMapping | Context
    ):
        super().__init__(name, **kwargs)  # pyright: ignore[reportArgumentType]
        self.source = source
        self.threads = threads
        self.reuse_pool = reuse_pool
        self._iter: Optional[Items] = None
        self.map: Callable[..., Iterator[Items]]
        self.pool = pool

        if self.name:
            self.pipe: SyncPipeline = import_module(f"riko.modules.{self.name}").pipe
            self.is_processor = bool(getattr(self.pipe, "type") == "processor")
            self.pollable: bool = getattr(self.pipe, "pollable")
            self.mapify = self.is_processor and self.source is not None
            self.parallelize: bool = self.parallel and self.mapify
        else:
            self.pipe = lambda source, **kw: source
            self.pollable = self.mapify = self.parallelize = False

        if self.parallelize:
            length = length_hint(self.source)
            def_pool = ThreadPool if self.threads else CPUPool

            self.workers = workers or get_worker_cnt(length, self.threads)
            self.chunksize = chunksize or get_chunksize(length, self.workers)
            self.pool = self.pool or def_pool(self.workers)
            self.map = self.pool.imap if ordered else self.pool.imap_unordered
        else:
            self.workers = workers
            self.chunksize = chunksize or 1
            self.map = map

    def __getattr__(self, name: str):
        if name in {"keys", "values", "items", "get"}:
            raise AttributeError
        else:
            kwargs = {
                "parallel": self.parallel,
                "threads": self.threads,
                "pool": self.pool if self.reuse_pool else None,
                "reuse_pool": self.reuse_pool,
                "workers": self.workers,
            }

            attr = SyncPipe(name, source=self, **kwargs)

        return attr

    def __iter__(self) -> Items:
        if self._iter is None:
            self._iter = self.fetch()

        return self._iter

    def __next__(self) -> ItemArg:
        if self._iter is None:
            self._iter = self.fetch()

        try:
            return next(self._iter)
        except StopIteration:
            if self.name == "send":
                others = cast(list[str], self.kwargs.get("others", []))
                [send(target, {"state": StreamState.DONE}) for target in others]

            raise

    def fetch(self) -> Items:
        pipeline = partial(self.pipe, **self.kwargs)

        if self.parallelize and self.source:
            source_items = list(self.source)
            zipped = zip(source_items, repeat(pipeline))
            mapped = self.map(listpipe, zipped, chunksize=self.chunksize)
        elif self.mapify and self.source:
            mapped = self.map(pipeline, self.source)
        else:
            mapped = None

        if mapped and self.parallelize and not self.reuse_pool:
            self.pool.close()
            self.pool.join()

        self._mapped = mapped
        pipeline = partial(self.pipe, **self.kwargs)
        yield from chain.from_iterable(self._mapped) if self._mapped else pipeline(self.source)

    @overload
    def export(self) -> list[ItemArg]:
        ...
    @overload  # noqa: E301, E302
    def export(self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs) -> int:
        ...
    def export(  # noqa: E301
        self,
        *args,
        **kwargs
    ) -> Optional[int | StringIO | Iterable[ItemArg]]:
        return export(self, *args, **kwargs)

    @property
    def list(self) -> list[ItemArg]:
        try:
            result = self.export()
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing SyncPipe attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result


class PyCollection(object):
    """A riko bulk url fetching object"""

    def __init__(self, sources: Iterable[BasicMapping], conf: Optional[ConfArg] = None, parallel=False, workers=None, **kwargs):
        # sources_1 = [{"url": "site.com/a"}, {"url": "site.com/b"}]
        # sources_2 = [
        #     {"url": "site.com/c", "type": "xpathfetchpage"},
        #     {"url": "site.com/d", "type": "xpathfetchpage"},
        # ]
        self.parallel = parallel
        self.conf = conf or cast(ConfArg, {})
        self.sources = sources
        self.length = length_hint(self.sources)
        self.workers = workers or get_worker_cnt(self.length)


class SyncCollection(PyCollection):
    """A synchronous PyCollection object"""

    def __init__(self, *args, threads: Optional[bool] = True, **kwargs):
        super(SyncCollection, self).__init__(*args, **kwargs)
        self.threads = threads
        self._iter: Optional[Items] = None
        self.map: Callable[..., Iterator[Iterator[Items]]]

        if self.parallel:
            self.chunksize = get_chunksize(self.length, self.workers)

            def_pool = ThreadPool if self.threads else CPUPool
            self.pool = def_pool(self.workers)
            self.map = self.pool.imap_unordered
        else:
            self.map = map

    def __iter__(self) -> Items:
        if self._iter is None:
            self._iter = self.fetch()

        return self._iter

    def __next__(self) -> ItemArg:
        if self._iter is None:
            self._iter = self.fetch()

        return next(self._iter)

    def fetch(self) -> Items:
        """Fetch all source urls"""
        zargs = zip(self.sources, repeat(self.conf))

        if self.parallel:
            mapped = self.map(fetch_source, zargs, chunksize=self.chunksize)
        else:
            mapped = self.map(fetch_source, zargs)

        for items in chain.from_iterable(mapped):
            yield from items

    def pipe(self, **kwargs):
        """Return a SyncPipe primed with the source feed"""
        return SyncPipe(source=self.fetch(), **kwargs)

    @overload
    def export(self) -> list[ItemArg]:
        ...
    @overload  # noqa: E301, E302
    def export(self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs) -> int:
        ...
    def export(  # noqa: E301
        self,
        *args,
        **kwargs
    ) -> Optional[int | StringIO | Iterable[ItemArg]]:
        return export(self, *args, **kwargs)

    @property
    def list(self):
        try:
            result = self.export()
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing SyncCollection attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""

    def __init__(
        self,
        name: Optional[str] = None,
        source: Optional[Deferred[Items]] = None,
        connections=16,
        **kwargs: BasicValue | BasicMapping | Context
    ):
        super().__init__(name, **kwargs)  # pyright: ignore[reportArgumentType]
        self.source = source
        self.connections = connections
        self._iter: Optional[Deferred[Items]] = None

        if self.name:
            self.module = import_module(f"riko.modules.{self.name}")
            self.async_pipe = self.module.async_pipe
            self.is_processor = self.async_pipe.type == "processor"
            self.mapify = self.is_processor and self.source
        else:
            self.async_pipe = lambda source, **kw: async_return(source)
            self.mapify = False

    def __getattr__(self, name):
        if name in {}:
            raise AttributeError
        else:
            attr = AsyncPipe(name, source=self.afetch(), connections=self.connections)

        return attr

    def __iter__(self) -> Deferred[Items]:
        if self._iter is None:
            self._iter = self.afetch()

        return self._iter

    @coroutine  # pyright: ignore[reportArgumentType]
    def afetch(self) -> Generator[Deferred[Items], Items, None]:
        if self.source:
            source = yield self.source
        else:
            source = None

        async_pipeline = partial(self.async_pipe, **self.kwargs)

        if self.mapify:
            args = (async_pipeline, source, self.connections)
            mapped = yield ait.async_map(*args)  # pyright: ignore[reportCallIssue]
            output = chain.from_iterable(mapped)
        else:
            output = yield async_pipeline(source)

        return_value(output)

    @property  # pyright: ignore[reportArgumentType]
    @coroutine  # pyright: ignore[reportArgumentType]
    def alist(self) -> Generator[Deferred[list[ItemArg]], list[ItemArg], None]:
        output = yield self.afetch()
        return_value(list(output))


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""

    def __init__(self, sources, connections=16, **kwargs):
        super(AsyncCollection, self).__init__(sources, **kwargs)
        self.connections = connections
        self._iter: Optional[Deferred[Items]] = None

    @coroutine
    def __iter__(self) -> Items:
        if self._iter is None:
            self._iter = yield self.afetch()

        return_value(self._iter)

    @coroutine
    def __next__(self) -> ItemArg:
        if self._iter is None:
            self._iter = yield self.afetch()

        return_value(next(self._iter))

    # pyright: ignore[reportArgumentType]
    @coroutine
    def afetch(self):
        """Fetch all source urls"""
        zargs = zip(self.sources, repeat(self.conf))
        mapped = yield ait.async_map(afetch_source, zargs, self.connections)  # pyright: ignore[reportCallIssue]
        chained = chain.from_iterable(mapped)
        return_value(chained)

    def async_pipe(self, **kwargs):
        """Return an AsyncPipe primed with the source feed"""
        return AsyncPipe(source=self.afetch(), **kwargs)

    @property  # pyright: ignore[reportArgumentType]
    @coroutine  # pyright: ignore[reportArgumentType]
    def alist(self):
        result = yield self.afetch()
        return_value(list(result))


def get_chunksize(length: int, workers: int) -> int:
    return (length // (workers * 4)) or 1


def get_worker_cnt(length: int, threads: Optional[bool] = True) -> int:
    multiplier = 2 if threads else 1
    return min(length or 1, cpu_count() * multiplier)


def listpipe(
    args: tuple[ItemArg, SyncPipeline],
    **kwargs: BasicValue
    # Mapping[str, StreamState] doesn't work with pyright for some reason
) -> Sequence[Mapping[str, object] | ComplexArg]:
    source, pipeline = args
    result = pipeline(source, **kwargs)
    return list(listize(result))


def fetch_source(
    args: tuple[Mapping[str, str], ConfArg],
    pipe: Optional[type[SyncPipe]] = SyncPipe,
) -> Iterator[Callable[..., SyncPipe]]:
    source, conf = args
    pipe_name = source.get("type", "fetch")
    result = pipe(pipe_name, conf=merge([conf, source]))
    return iter(listize(result))


def afetch_source(
    args: tuple[Mapping[str, str], ConfArg],
    pipe: Optional[type[AsyncPipe]] = AsyncPipe,
) -> Iterable[Callable[..., AsyncPipe]]:
    source, conf = args
    pipe_name = source.get("type", "fetch")
    result = pipe(pipe_name, conf=merge([conf, source]))
    return result.alist


@coroutine
def alistpipe(args):
    source, async_pipeline = args
    output = yield async_pipeline(source)
    return_value(list(output))
