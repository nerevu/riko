# vim: sw=4:ts=4:expandtab
"""
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
        >>> list(SyncPipe('fetchdata', conf=fconf)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ... )
        [{'count': 169}]
        >>> list(SyncPipe('fetchdata', conf=fconf, parallel=True)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ... )
        [{'count': 169}]
        >>> list(SyncPipe('fetchdata', conf=fconf, parallel=True, threads=False)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ... )
        [{'count': 169}]
        >>> fconf['type'] = 'fetchdata'
        >>> sources = [{'url': get_path('feed.xml')}, fconf]
        >>> stream = SyncCollection(sources)
        >>> next(stream)['title']
        'Donations'
        >>> len(list(stream))
        55
        >>> len(list(SyncCollection(sources, parallel=True)))
        56

    async usage::

        >>> from riko import get_path
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.collections import AsyncPipe, AsyncCollection
        >>>
        >>> fconf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'field': 'title'}}
        >>>
        >>> async def run(reactor):
        ...     d = await (AsyncPipe('fetchdata', conf=fconf)
        ...         .sort(conf=sort_conf)
        ...         .tokenizer(conf=str_conf, **str_kwargs)
        ...         .count()
        ...     )
        ...
        ...     print(list(d))
        ...
        >>> if _issync:
        ...     [{'count': 169}]
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        [{'count': 169}]
        >>> async def run(reactor):
        ...     fconf['type'] = 'fetchdata'
        ...     sources = [{'url': get_path('feed.xml')}, fconf]
        ...     s = await AsyncCollection(sources)
        ...     d = list(s)
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

from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Iterator,
    Mapping,
)
from functools import partial
from importlib import import_module
from io import StringIO
from itertools import chain, repeat
from multiprocessing import Pool as CPUPool
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from operator import length_hint
from typing import TYPE_CHECKING, Any, Literal, cast, overload

import pygogo as gogo

from riko import listize

try:
    from csv2ofx.ofx import OFX
except ModuleNotFoundError:
    mapping = OFX = QIF = gen_data = None
else:
    from csv2ofx.mappings.default import mapping
    from csv2ofx.qif import QIF
    from csv2ofx.utils import gen_data

from meza import convert as cv
from meza import io

from riko import Context
from riko.bado import async_return
from riko.bado.itertools import async_map
from riko.types.general import (
    AsyncPipeParser,
    Conf,
    ConversionFunc,
    Item,
    Items,
    ParserOutput,
    SplitterParserOutput,
    Stream,
    SyncPipeParser,
)
from riko.types.values import BasicValue, StreamState
from riko.utils import send

if TYPE_CHECKING:
    from multiprocessing.dummy import Pool as ThreadPoolType
    from multiprocessing.pool import Pool as CPUPoolType

type AnyPool = "ThreadPoolType" | "CPUPoolType"


logger = gogo.Gogo(__name__, monolog=True).logger


def records2ofx(items, **_) -> Iterable[str]:
    ofx = OFX(mapping)
    groups = ofx.gen_groups(items)
    trxns = ofx.gen_trxns(groups)
    cleaned_trxns = ofx.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(ofx.header(), ofx.gen_body(data), ofx.footer())


def records2qif(items, **_) -> Iterable[str]:
    qif = QIF(mapping)
    groups = qif.gen_groups(items)
    trxns = qif.gen_trxns(groups)
    cleaned_trxns = qif.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(qif.gen_body(data), qif.footer())


CONVERSION_FUNCS: dict[str, ConversionFunc] = {
    # "array": cv.records2array,
    "csv": cv.records2csv,
    # "dataframe": cv.records2df,
    "geojson": cv.records2geojson,
    # 'ical': cv.records2ical,
    "json": cv.records2json,
    # 'kml': cv.records2kml,
    "list": lambda items, **kw: list(items),
    "tuple": lambda items, **kw: tuple(items),
}

if OFX is not None:
    CONVERSION_FUNCS["ofx"] = cast(ConversionFunc, records2ofx)
    CONVERSION_FUNCS["qif"] = cast(ConversionFunc, records2qif)


@overload
def export(items) -> list[Item]: ...  # noqa: E704
@overload
def export(items, **kwargs) -> list[Item]: ...  # noqa: E704
@overload  # noqa: E302
def export(  # noqa: E704
    items, _type: Literal["list"], **kwargs
) -> list[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items, _type: Literal["tuple"], **kwargs
) -> tuple[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items, _type: Literal["csv", "json", "geojson"], f: str, **kwargs
) -> int: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items, _type: Literal["csv", "json", "geojson"], f: None = ..., **kwargs
) -> StringIO: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items, _type: str = ..., **kwargs
) -> StringIO | Items | None: ...
def export(  # noqa: E302
    items: Stream, _type: str = "list", f: str | None = None, **kwargs
) -> int | StringIO | Items | None:
    result = None

    if converter := CONVERSION_FUNCS.get(_type):
        _result = converter(items, **kwargs)

        if f:
            result = cast(int, io.write(f, _result, **kwargs))
        else:
            result = _result
    else:
        logger.error(
            f"Invalid type, {_type}. You must supply one of {CONVERSION_FUNCS}."
        )

    return result


class PyPipe:
    """
    A riko module fetching object

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
        name: str | None = None,
        parallel=False,
        inputs: Mapping | None = None,
        context: Context | None = None,
        conf: Conf = None,
        **kwargs,
    ):
        self.name = name
        self.parallel = parallel
        self.inputs = inputs or {}
        self.verbose = kwargs.get("verbose")
        self.test = kwargs.get("test")
        self.conf = conf or {}
        self.context = context or Context(**kwargs)
        self.describe_input = self.context.describe_input
        self.describe_dependencies = self.context.describe_dependencies
        self.kwargs = kwargs
        updates = {"conf": self.conf, "inputs": self.inputs, "context": self.context}
        self.kwargs.update(updates)

    def __call__(self, **kwargs):
        self.kwargs.update(kwargs)
        return self


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""

    def __init__(
        self,
        name: str | None = None,
        parallel: bool = False,
        inputs: Mapping | None = None,
        context: Context | None = None,
        conf: Conf = None,
        source: Items | None = None,
        workers: int | None = None,
        chunksize: int | None = None,
        threads: bool | None = True,
        reuse_pool: bool | None = True,
        pool: AnyPool | None = None,
        ordered: bool | None = False,
        **kwargs,
    ):
        super().__init__(
            name, parallel=parallel, inputs=inputs, context=context, conf=conf, **kwargs
        )
        self.source = source
        self.threads = threads
        self.reuse_pool = reuse_pool
        self._iter: Stream | None = None
        self.map: Callable[..., Iterator[Stream]]
        self.pool = pool

        if self.name:
            self.pipe: SyncPipeParser = import_module(f"riko.modules.{self.name}").pipe
            pipe_type = getattr(self.pipe, "type")  # noqa: B009
            self.is_processor = bool(pipe_type == "processor")
            self.pollable: bool = getattr(self.pipe, "pollable")  # noqa: B009
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
        if name.startswith("_") or name in {"keys", "values", "items", "get"}:
            raise AttributeError(name)

        kwargs = {
            "parallel": self.parallel,
            "threads": self.threads,
            "pool": self.pool if self.reuse_pool else None,
            "reuse_pool": self.reuse_pool,
            "workers": self.workers,
        }

        return SyncPipe(name, source=self, **kwargs)

    def _stream(self) -> Stream:
        pipeline = partial(self.pipe, **self.kwargs)

        if self.parallelize and self.source is not None:
            source_items = list(self.source)
            zipped = zip(source_items, repeat(pipeline))
            mapped = self.map(listpipe, zipped, chunksize=self.chunksize)
        elif self.mapify and self.source is not None:
            mapped = self.map(pipeline, self.source)
        else:
            mapped = None

        if mapped and self.parallelize and not self.reuse_pool:
            self.pool.close()
            self.pool.join()

        self._mapped = mapped

        if self._mapped:
            yield from chain.from_iterable(self._mapped)
        else:
            yield from pipeline(self.source)

    def __iter__(self) -> Stream:
        if self._iter is None:
            self._iter = self._stream()

        return self._iter

    def __next__(self) -> Item:
        if self._iter is None:
            self._iter = self._stream()

        try:
            return next(self._iter)
        except StopIteration:
            self._iter = None

            if self.name == "send":
                others = cast(list[str], self.kwargs.get("others", []))
                [send(target, {"state": StreamState.DONE}) for target in others]

            raise

    def split(self, **kwargs) -> SplitterParserOutput:
        pipe_kwargs = {
            "parallel": self.parallel,
            "threads": self.threads,
            "pool": self.pool if self.reuse_pool else None,
            "reuse_pool": self.reuse_pool,
            "workers": self.workers,
        }

        splits = SyncPipe("split", source=self, **pipe_kwargs, **kwargs)
        return cast(SplitterParserOutput, splits)

    @overload
    def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    def export(  # noqa: E704
        self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs
    ) -> int: ...
    def export(  # noqa: E301
        self, *args, **kwargs
    ) -> int | StringIO | Items | None:
        try:
            result = export(self, *args, **kwargs)
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing SyncPipe attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result


class PyCollection:
    """A riko bulk url fetching object"""

    def __init__(
        self,
        sources: Iterable[Mapping[str, str]],
        conf: Conf = None,
        parallel=False,
        workers=None,
        **kwargs,
    ):
        # sources_1 = [{"url": "site.com/a"}, {"url": "site.com/b"}]
        # sources_2 = [
        #     {"url": "site.com/c", "type": "xpathfetchpage"},
        #     {"url": "site.com/d", "type": "xpathfetchpage"},
        # ]
        self.parallel = parallel
        self.conf = conf or cast(Conf, {})
        self.sources = sources
        self.length = length_hint(self.sources)
        self.workers = workers or get_worker_cnt(self.length)


class SyncCollection(PyCollection):
    """A synchronous PyCollection object"""

    def __init__(self, *args, threads: bool | None = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.threads = threads
        self._iter: Stream | None = None
        self.map: Callable[..., Iterator[Stream]]

        if self.parallel:
            self.chunksize = get_chunksize(self.length, self.workers)

            def_pool = ThreadPool if self.threads else CPUPool
            self.pool = def_pool(self.workers)
            self.map = self.pool.imap_unordered
        else:
            self.map = map

    def __iter__(self) -> Stream:
        if self._iter is None:
            self._iter = self._stream()

        return self._iter

    def __next__(self) -> Item:
        if self._iter is None:
            self._iter = self._stream()

        return next(self._iter)

    def _stream(self) -> Stream:
        """Fetch all source urls"""
        zargs = zip(self.sources, repeat(self.conf))

        if self.parallel:
            mapped = self.map(fetch_source, zargs, chunksize=self.chunksize)
        else:
            mapped = self.map(fetch_source, zargs)

        yield from chain.from_iterable(mapped)

    def pipe(self, **kwargs):
        """Return a SyncPipe primed with the source feed"""
        return SyncPipe(source=self._stream(), **kwargs)

    @overload
    def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    def export(  # noqa: E704
        self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs
    ) -> int: ...
    def export(  # noqa: E301
        self, *args, **kwargs
    ) -> int | StringIO | Items | None:
        return export(self, *args, **kwargs)


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""

    def __init__(
        self,
        name: str | None = None,
        parallel: bool = False,
        inputs: Mapping | None = None,
        context: Context | None = None,
        conf: Conf = None,
        source: Awaitable[Items] | None = None,
        connections=16,
        **kwargs,
    ):
        super().__init__(
            name, parallel=parallel, inputs=inputs, context=context, conf=conf, **kwargs
        )
        self.source = source
        self.connections = connections
        self._aiter: AsyncIterator[Item] | None = None

        if self.name:
            self.module = import_module(f"riko.modules.{self.name}")
            self.async_pipe: AsyncPipeParser = self.module.async_pipe
            pipe_type = getattr(self.async_pipe, "type")  # noqa: B009
            self.is_processor = bool(pipe_type == "processor")
            self.mapify = self.is_processor
        else:
            self.async_pipe = lambda source, **kw: async_return(source)
            self.mapify = False

    async def _await_stream(self) -> Stream:
        """Converts the AsyncIterator stream to an Awaitable"""
        return iter([item async for item in self._stream()])

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        kwargs = {"source": self._await_stream(), "connections": self.connections}
        return AsyncPipe(name, **kwargs)

    def __await__(self) -> Generator[Any, None, Stream]:
        return self._await_stream().__await__()

    def __aiter__(self) -> AsyncIterator[Item]:
        if self._aiter is None:
            self._aiter = self._stream()

        return self._aiter

    async def __anext__(self) -> Item:
        if self._aiter is None:
            self._aiter = self._stream()

        try:
            return await anext(self._aiter)
        except StopAsyncIteration:
            self._aiter = None
            raise

    async def _stream(self) -> AsyncIterator[Item]:
        source = await self.source if self.source else None
        async_pipeline = partial(self.async_pipe, **self.kwargs)

        if self.mapify and source:
            mapped = await async_map(async_pipeline, source, self.connections)

            for stream in mapped:
                for item in stream:
                    yield item
        else:
            result = await async_pipeline(source)

            for item in result:
                yield item

    async def split(self, **kwargs) -> SplitterParserOutput:
        pipe_kwargs = {"source": self._await_stream(), "connections": self.connections}
        result = await AsyncPipe("split", **pipe_kwargs, **kwargs)
        return cast(SplitterParserOutput, result)


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""

    def __init__(
        self,
        sources,
        connections=16,
        conf: Conf = None,
        parallel: bool = False,
        **kwargs,
    ):
        super().__init__(sources, conf=conf, parallel=parallel, **kwargs)
        self.connections = connections
        self._aiter: AsyncIterator[Item] | None = None

    async def _stream(self) -> AsyncIterator[Item]:
        """Fetch all source urls"""
        zargs = zip(self.sources, repeat(self.conf))
        mapped = await async_map(afetch_source, zargs, self.connections)

        for stream in mapped:
            for item in stream:
                yield item

    async def _await_stream(self) -> Stream:
        """Converts the AsyncIterator stream to an Awaitable"""
        return iter([item async for item in self._stream()])

    def __await__(self) -> Generator[Any, None, Stream]:
        return self._await_stream().__await__()

    def __aiter__(self) -> AsyncIterator[Item]:
        if self._aiter is None:
            self._aiter = self._stream()

        return self._aiter

    async def __anext__(self) -> Item:
        if self._aiter is None:
            self._aiter = self._stream()

        try:
            return await anext(self._aiter)
        except StopAsyncIteration:
            self._aiter = None
            raise

    def async_pipe(self, **kwargs):
        """Return an AsyncPipe primed with the source feed"""
        return AsyncPipe(source=self._await_stream(), **kwargs)


def get_chunksize(length: int, workers: int) -> int:
    return (length // (workers * 4)) or 1


def get_worker_cnt(length: int, threads: bool | None = True) -> int:
    multiplier = 2 if threads else 1
    maximum = cpu_count() * multiplier
    return min(length, maximum) if length else maximum


def listpipe(
    args: tuple[Item, SyncPipeParser], **kwargs: BasicValue
) -> list[ParserOutput]:
    source, pipeline = args
    result = pipeline(source, **kwargs)
    return list(listize(result))


def fetch_source(
    args: tuple[Mapping[str, str], Conf], pipe: type[SyncPipe] = SyncPipe
) -> Stream:
    source, _conf = args
    conf = {**_conf, **source}
    pipe_name = source.get("type", "fetch")
    primed_pipe = pipe(pipe_name, conf=cast(Conf, conf))
    return iter(primed_pipe)


async def afetch_source(
    args: tuple[Mapping[str, str], Conf], pipe: type[AsyncPipe] = AsyncPipe
) -> Stream:
    source, _conf = args
    conf = {**_conf, **source}
    pipe_name = str(source.get("type", "fetch"))
    return await pipe(pipe_name, conf=cast(Conf, conf))
