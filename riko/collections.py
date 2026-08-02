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
        >>> from riko.bado import run, issync
        >>> from riko.collections import AsyncPipe, AsyncCollection
        >>>
        >>> fconf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> str_conf = {'delimiter': '<br>'}
        >>> str_kwargs = {'field': 'description', 'emit': True}
        >>> sort_conf = {'rule': {'field': 'title'}}
        >>>
        >>> async def main():
        ...     d = await (AsyncPipe('fetchdata', conf=fconf)
        ...         .sort(conf=sort_conf)
        ...         .tokenizer(conf=str_conf, **str_kwargs)
        ...         .count()
        ...     )
        ...
        ...     print(list(d))
        ...
        >>> if issync:
        ...     [{'count': 169}]
        ... else:
        ...     run(main)
        [{'count': 169}]
        >>> async def main():
        ...     fconf['type'] = 'fetchdata'
        ...     sources = [{'url': get_path('feed.xml')}, fconf]
        ...     s = await AsyncCollection(sources)
        ...     d = list(s)
        ...     print(d[0]['title'])
        ...     print(len(d))
        ...
        >>> if issync:
        ...     print("Donations")
        ...     print(56)
        ... else:
        ...     run(main)
        Donations
        56

"""

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Mapping,
)
from enum import StrEnum
from functools import partial
from inspect import isawaitable
from io import StringIO
from itertools import chain, repeat
from logging import Logger
from multiprocessing import Pool as CPUPool
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from operator import length_hint
from typing import Any, Literal, Self, cast, overload

import pygogo as gogo

from riko import listize
from riko.context import ExecutionMode

try:
    from csv2ofx.ofx import OFX
except ModuleNotFoundError:
    mapping = OFX = QIF = gen_data = None
else:
    from csv2ofx.mappings.default import mapping
    from csv2ofx.qif import QIF
    from csv2ofx.utils import gen_data

from multiprocessing.pool import Pool as CPUPoolType
from multiprocessing.pool import ThreadPool as ThreadPoolType

from meza import convert as cv
from meza import io

from riko import Context
from riko._pubsub import sync_hub
from riko.bado import async_return
from riko.bado.itertools import async_iter, async_map
from riko.compile import resolve_module
from riko.exceptions import PipelineStateError
from riko.types.general import (
    AsyncItems,
    AsyncPipeParser,
    AsyncStream,
    Conf,
    ConversionFunc,
    Function,
    Item,
    Items,
    ParserOutput,
    SkipIf,
    SplitterParserOutput,
    Stream,
    SyncPipeParser,
)
from riko.types.values import BasicValue, Inputs
from riko.utils import parse_context

type AnyPool = ThreadPoolType | CPUPoolType

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "SyncCollection",
    "SyncPipe",
    "export",
    "list_targets",
]


class PoolScope(StrEnum):
    STAGE = "stage"
    PIPELINE = "pipeline"


class PipeState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    EXHAUSTED = "exhausted"
    CLOSED = "closed"
    FAILED = "failed"


class _Lifecycle:
    """
    One-shot execution state shared by pipes and collections. An instance
    represents a single execution: iteration is a plain memoized generator, so
    re-iterating an already-run instance yields nothing (ordinary spent-iterator
    semantics), and chaining a started or exhausted instance wraps whatever
    source is left. The mixin only tracks that state for introspection
    (``state``, ``closed``, ``exhausted``, ``failed``) and refuses to chain onto
    an instance whose resources are gone, raising ``PipelineStateError`` when it
    is ``CLOSED`` or ``FAILED``.
    """

    _state: PipeState = PipeState.NEW

    @property
    def state(self) -> PipeState:
        return self._state

    @property
    def closed(self) -> bool:
        return self._state is PipeState.CLOSED

    @property
    def exhausted(self) -> bool:
        return self._state is PipeState.EXHAUSTED

    @property
    def failed(self) -> bool:
        return self._state is PipeState.FAILED

    def _begin(self) -> None:
        if self._state is PipeState.NEW:
            self._state = PipeState.RUNNING

    def _end(self) -> None:
        if self._state is PipeState.RUNNING:
            self._state = PipeState.EXHAUSTED

    def _fail(self) -> None:
        self._state = PipeState.FAILED

    def _close(self) -> None:
        self._state = PipeState.CLOSED

    def _require_usable(self, action: str) -> None:
        if self._state in {PipeState.CLOSED, PipeState.FAILED}:
            raise PipelineStateError(self._state.value, action)


class _PoolHandle:
    """Shared pool state, including whether riko owns the pool."""

    def __init__(self, pool: AnyPool, *, owned: bool) -> None:
        self.pool: AnyPool | None = pool
        self.owned = owned

    def __bool__(self) -> bool:
        return self.pool is not None

    def close(self) -> None:
        if self.owned and (pool := self.pool):
            pool.close()
            pool.join()
            self.pool = None

    def terminate(self) -> None:
        if self.owned and (pool := self.pool):
            pool.terminate()
            pool.join()
            self.pool = None


def records2ofx(items: Items, **_: object) -> Iterable[str]:
    ofx = OFX(mapping)
    groups = ofx.gen_groups(items)
    trxns = ofx.gen_trxns(groups)
    cleaned_trxns = ofx.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(ofx.header(), ofx.gen_body(data), ofx.footer())


def records2qif(items: Items, **_: object) -> Iterable[str]:
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
    "list": lambda items, **_: list(items),
    "tuple": lambda items, **_: tuple(items),
}

if OFX is not None:
    CONVERSION_FUNCS["ofx"] = cast(ConversionFunc, records2ofx)
    CONVERSION_FUNCS["qif"] = cast(ConversionFunc, records2qif)


def list_targets() -> tuple[str, ...]:
    return tuple(sorted(CONVERSION_FUNCS))


@overload
def export(items: Items) -> list[Item]: ...  # noqa: E704
@overload
def export(items: Items, **kwargs: Any) -> list[Item]: ...  # noqa: E704
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, _type: Literal["list"], **kwargs: Any
) -> list[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, _type: Literal["tuple"], **kwargs: Any
) -> tuple[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, _type: Literal["csv", "json", "geojson"], f: str, **kwargs: Any
) -> int: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    _type: Literal["csv", "json", "geojson"],
    f: None = ...,
    **kwargs: Any,
) -> StringIO: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, _type: str = ..., **kwargs: Any
) -> StringIO | Items | None: ...
def export(  # noqa: E302
    items: Items, _type: str = "list", f: str | None = None, **kwargs: Any
) -> int | StringIO | Items | None:
    result = None

    if converter := CONVERSION_FUNCS.get(_type):
        _result = converter(items, **kwargs)

        if f:
            result = cast(int, io.write(f, _result, **kwargs))
        else:
            result = _result
    else:
        valid = ", ".join(CONVERSION_FUNCS)
        raise ValueError(f"Invalid export type {_type!r}. Must be one of: {valid}.")

    return result


class PyPipe(_Lifecycle):
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
        source: AsyncItems | Awaitable[Items] | Items | None = None,
        *,
        assign: str | None = None,
        conf: Conf | None = None,
        context: Context | None = None,
        field: str | None = None,
        func: Function | None = None,
        inputs: Inputs | None = None,
        mode: ExecutionMode | None = None,
        others: Iterable[str] | Iterable[Stream] | None = None,
        parallel: bool = False,
        skip_if: SkipIf | None = None,
        submodule: bool | None = False,
        test: bool | None = False,
        verbose: bool | None = False,
        **kwargs: object,
    ):

        self._state = PipeState.NEW
        self.name = name
        self.source = source
        self.parallel = parallel
        self.conf: Conf = conf or {}
        self.context: Context = parse_context(
            context,
            mode=mode,
            inputs=inputs,
            verbose=verbose,
            test=test,
            submodule=submodule,
            describe_input=bool(kwargs.get("describe_input")),
            describe_dependencies=bool(kwargs.get("describe_dependencies")),
        )
        self.inputs: Inputs = self.context.inputs
        self.verbose: bool = bool(verbose)
        self.test: bool = bool(test)
        self.describe_input: bool = self.context.describe_input
        self.describe_dependencies: bool = self.context.describe_dependencies
        self.kwargs = kwargs
        updates = {
            "assign": assign,
            "conf": self.conf,
            "context": self.context,
            "field": field,
            "func": func,
            "inputs": self.inputs,
            "mode": mode,
            "others": others,
            "skip_if": skip_if,
        }
        self.kwargs.update(updates)

    def __call__(
        self,
        context: Context | None = None,
        conf: Conf | None = None,
        *,
        assign: str | None = None,
        field: str | None = None,
        func: Function | None = None,
        inputs: Inputs | None = None,
        mode: ExecutionMode | None = None,
        others: Iterable[str] | Iterable[Stream] | None = None,
        skip_if: SkipIf | None = None,
        **kwargs: object,
    ) -> Self:
        updates = {
            "assign": assign,
            "conf": conf,
            "context": context,
            "field": field,
            "func": func,
            "inputs": inputs,
            "mode": mode,
            "others": others,
            "skip_if": skip_if,
        }
        self.kwargs.update(updates)
        self.kwargs.update(kwargs)
        return self

    def _notify_subscribers(self) -> None:
        if self.name == "send":
            ids = cast(dict[str, int], self.kwargs.get("ids", {}))
            sync_hub.notify_complete(ids)


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""

    def __init__(
        self,
        name: str | None = None,
        source: Items | None = None,
        conf: Conf | None = None,
        *,
        _pool_handle: _PoolHandle | None = None,
        assign: str | None = None,
        chunksize: int | None = None,
        context: Context | None = None,
        field: str | None = None,
        func: Function | None = None,
        inputs: Inputs | None = None,
        mode: ExecutionMode | None = None,
        ordered: bool | None = False,
        others: Iterable[str] | Iterable[Stream] | None = None,
        parallel: bool = False,
        pool: AnyPool | None = None,
        pool_scope: PoolScope = PoolScope.PIPELINE,
        skip_if: SkipIf | None = None,
        submodule: bool | None = False,
        test: bool | None = False,
        threads: bool | None = True,
        verbose: bool | None = False,
        workers: int | None = None,
        **kwargs: object,
    ):
        super().__init__(
            name,
            source,
            assign=assign,
            conf=conf,
            context=context,
            field=field,
            func=func,
            inputs=inputs,
            mode=mode,
            others=others,
            parallel=parallel,
            skip_if=skip_if,
            submodule=submodule,
            test=test,
            verbose=verbose,
            **kwargs,
        )
        self.threads: bool = bool(threads)
        self.pool_scope: PoolScope = pool_scope
        self.ordered = ordered
        self._iter: Generator[Item, None, None] | None = None
        self._mapped: Iterable[Stream] | None = None
        self._in_context: bool = False
        self._terminal: bool = True
        self.source: Items = cast(Items, self.source)

        self.map: Callable[..., Iterable[Stream]]

        if pool_scope not in {"stage", "pipeline"}:
            raise ValueError("pool_scope must be either 'stage' or 'pipeline'")

        if pool and _pool_handle:
            raise TypeError("pool and _pool_handle cannot both be provided")
        elif pool:
            self._pool_handle: _PoolHandle | None = _PoolHandle(pool, owned=False)
        else:
            self._pool_handle = _pool_handle

        if self.name:
            self.pipe: SyncPipeParser = resolve_module(self.name, "pipe")
            self.pollable: bool = getattr(self.pipe, "pollable")  # noqa: B009
            self.loopable: bool = getattr(self.pipe, "loopable")  # noqa: B009
            self.mapify: bool = self.loopable and self.source is not None
            self.parallelize: bool = self.parallel and self.mapify
        else:
            self.pipe = lambda source, **_: source
            self.pollable = self.loopable = self.mapify = self.parallelize = False

        if self.parallelize:
            length = length_hint(self.source)
            def_pool = ThreadPool if self.threads else CPUPool
            self.workers: int | None = workers or get_worker_cnt(length, self.threads)
            self.chunksize: int = chunksize or get_chunksize(length, self.workers)

            if not self._pool_handle:
                new_pool = cast(AnyPool, def_pool(self.workers))
                self._pool_handle = _PoolHandle(new_pool, owned=True)

            if not (pool := self.pool):
                raise RuntimeError("Cannot reuse a closed worker pool")

            self.map = pool.map if ordered else pool.imap_unordered
        else:
            self.workers = workers
            self.chunksize = chunksize or 1
            self.map = map

    @property
    def pool(self) -> AnyPool | None:
        return self._pool_handle.pool if self._pool_handle else None

    def _chain(self, name: str, **kwargs: object) -> "SyncPipe":
        """
        Create the next pipe stage, propagating all runtime and execution
        settings. Context (and its inputs) stays authoritative across the chain.

        Examples:
            >>> conf = {'key': 'a', 'value': 'b'}
            >>> flow = SyncPipe('itembuilder', conf=conf, inputs={'x': '1'})
            >>> chained = flow.hash()
            >>> str(chained.context) == str(flow.context)
            True
            >>> chained.inputs == flow.inputs == flow.context.inputs
            True

        """
        self._require_usable("chain")
        next_scope = cast(PoolScope, kwargs.get("pool_scope", self.pool_scope))

        skwargs = {
            "parallel": self.parallel,
            "threads": self.threads,
            "pool_scope": next_scope,
            "workers": self.workers,
            "chunksize": self.chunksize,
            "context": self.context,
            "inputs": self.inputs,
        }

        if self.pool_scope == next_scope == PoolScope.PIPELINE and "pool" not in kwargs:
            shared_handle = self._pool_handle
            skwargs["_pool_handle"] = shared_handle
        else:
            shared_handle = None

        skwargs.update(kwargs)
        child = SyncPipe(name, source=self, **skwargs)

        # Transfer cleanup responsibility only after successful construction
        # and only when the handle was actually shared.
        if shared_handle and child._pool_handle is shared_handle:
            self._terminal = False

        return child

    def __getattr__(self, name: str) -> "SyncPipe":
        if name.startswith("_") or name in {"keys", "values", "items", "get"}:
            raise AttributeError(name)

        return self._chain(name)

    def _release_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.close()

    def _terminate_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.terminate()

    def close(self) -> None:
        if self._iter is not None:
            self._iter.close()

        self._release_pool()
        self._close()

    def terminate(self) -> None:
        if self._iter is not None:
            self._iter.close()

        self._terminate_pool()
        self._close()

    def __enter__(self) -> Self:
        """
        Use a pipe as a context manager. When a parallel pipe creates its own
        thread/process pool, that pool is shut down when the block exits (or
        terminated if the block raises). A pool passed in by the caller is left
        running.

        Examples:
            >>> src = [{'content': 'a'}, {'content': 'b'}]
            >>>
            >>> with (flow := SyncPipe('hash', source=src, parallel=True)):
            ...     results = list(flow)
            ...     flow.pool  # the worker pool is live inside the block
            <multiprocessing.pool.ThreadPool state=RUN pool_size=2>
            >>> flow.pool  # ... and shut down once the block exits
            >>> len(results)
            2
            >>> # the pool is *terminated* if the block raises
            >>> try:
            ...     with (flow := SyncPipe('hash', source=src, parallel=True)):
            ...         raise RuntimeError('boom')
            ... except RuntimeError:
            ...     pass
            >>> flow.pool

        """
        self._in_context = True
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, *_: object
    ) -> Literal[False]:
        self._in_context = False
        self.close() if exc_type is None else self.terminate()
        return False

    def _release_pool_after_iteration(self) -> bool:
        if self._in_context:
            result = False
        elif self.pool_scope == PoolScope.STAGE:
            result = True
        else:
            result = self._terminal

        return result

    def _stream(self) -> Generator[Item, None, None]:
        if self.name == "send":
            self.kwargs.setdefault("ids", {})

        self._begin()
        pipeline = partial(self.pipe, **self.kwargs)

        try:
            if self.parallelize and self.source is not None:
                source_items = list(self.source)
                zipped = zip(source_items, repeat(pipeline))
                mapped = self.map(listpipe, zipped, chunksize=self.chunksize)
            elif self.mapify and self.source is not None:
                mapped = self.map(pipeline, self.source)
            else:
                mapped = None

            self._mapped = mapped

            if self._mapped is None:
                yield from pipeline(self.source)
            else:
                yield from chain.from_iterable(self._mapped)
        except BaseException:
            self._fail()

            if self._release_pool_after_iteration():
                self._terminate_pool()

            raise
        finally:
            if self._release_pool_after_iteration():
                self._release_pool()

            self._end()
            self._notify_subscribers()

    def __iter__(self) -> Stream:
        if self._iter is None:
            self._iter = self._stream()

        return self._iter

    def __next__(self) -> Item:
        if self._iter is None:
            self._iter = self._stream()

        return next(self._iter)

    def split(self, **kwargs: object) -> SplitterParserOutput:
        splits = self._chain("split", **kwargs)
        return cast(SplitterParserOutput, splits)

    @overload
    def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    def export(  # noqa: E704
        self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | StringIO | Items | None:
        try:
            result = export(self, *args, **kwargs)
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing SyncPipe attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result


class PyCollection(_Lifecycle):
    """A riko bulk url fetching object"""

    def __init__(
        self,
        sources: Iterable[Mapping[str, str]],
        *,
        conf: Conf | None = None,
        workers: int | None = None,
        parallel: bool = False,
        **_: object,
    ):
        self._state = PipeState.NEW
        self.parallel: bool = parallel
        self.conf: Conf = conf or cast(Conf, {})
        self.sources: Iterable[Mapping[str, str]] = sources
        self.length: int = length_hint(self.sources)
        self.workers: int = workers or get_worker_cnt(self.length)


class SyncCollection(PyCollection):
    """
    A synchronous PyCollection object

    Examples:
        >>> from riko import get_path
        >>> sources = [{'url': get_path(f)} for f in ['feed.xml', 'gawker.xml']]
        >>> stream = SyncCollection(sources, parallel=True)
        >>> len(list(stream))
        32

    """

    def __init__(
        self,
        sources: Iterable[Mapping[str, str]],
        *,
        conf: Conf | None = None,
        workers: int | None = None,
        parallel: bool = False,
        threads: bool | None = True,
        ordered: bool | None = False,
        pool: AnyPool | None = None,
        **kwargs: object,
    ):
        super().__init__(
            sources, conf=conf, workers=workers, parallel=parallel, **kwargs
        )
        self.threads: bool = bool(threads)
        self.ordered: bool = bool(ordered)
        self._iter: Stream | None = None
        self.map: Callable[..., Iterable[Stream]]
        self._in_context: bool = False
        self._pool_handle: _PoolHandle | None = (
            _PoolHandle(pool, owned=False) if pool else None
        )

        if self.parallel:
            self.chunksize: int = get_chunksize(self.length, self.workers)
            def_pool = ThreadPool if self.threads else CPUPool

            if not self._pool_handle:
                new_pool = cast(AnyPool, def_pool(self.workers))
                self._pool_handle = _PoolHandle(new_pool, owned=True)

            if not (pool := self.pool):
                raise RuntimeError("Cannot reuse a closed worker pool")

            self.map = pool.map if ordered else pool.imap_unordered
        else:
            self.map = map

    @property
    def pool(self) -> AnyPool | None:
        return self._pool_handle.pool if self._pool_handle else None

    def __iter__(self) -> Stream:
        if self._iter is None:
            self._iter = self._stream()

        return self._iter

    def __next__(self) -> Item:
        if self._iter is None:
            self._iter = self._stream()

        return next(self._iter)

    def _release_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.close()

    def _terminate_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.terminate()

    def close(self) -> None:
        self._release_pool()
        self._close()

    def terminate(self) -> None:
        self._terminate_pool()
        self._close()

    def __enter__(self) -> Self:
        """
        Use a collection as a context manager. A parallel collection creates its
        own thread/process pool, which is shut down when the block exits (or
        terminated if the block raises).

        Examples:
            >>> from riko import get_path
            >>> sources = [{'url': get_path(f)} for f in ['feed.xml', 'gawker.xml']]
            >>>
            >>> with (stream := SyncCollection(sources, parallel=True)):
            ...     results = list(stream)
            ...     stream.pool  # the worker pool is live inside the block
            <multiprocessing.pool.ThreadPool state=RUN pool_size=2>
            >>> stream.pool  # ... and shut down once the block exits
            >>> len(results)
            32
            >>> # the pool is *terminated* if the block raises
            >>> try:
            ...     with (stream := SyncCollection(sources, parallel=True)):
            ...         raise RuntimeError('boom')
            ... except RuntimeError:
            ...     pass
            >>> stream.pool

        """
        self._in_context = True
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, *_: object
    ) -> Literal[False]:
        self._in_context = False
        self.close() if exc_type is None else self.terminate()
        return False

    def _stream(self) -> Stream:
        """Fetch all source urls"""
        self._begin()

        try:
            zargs = zip(self.sources, repeat(self.conf))

            if self.parallel:
                mapped = self.map(fetch_source, zargs, chunksize=self.chunksize)
            else:
                mapped = self.map(fetch_source, zargs)

            yield from chain.from_iterable(mapped)
        except BaseException:
            self._fail()

            if not self._in_context:
                self._terminate_pool()

            raise
        else:
            self._end()

            if not self._in_context:
                self._release_pool()

    def pipe(self, **kwargs: Any) -> "SyncPipe":
        """Return a SyncPipe primed with the source feed"""
        return SyncPipe(source=self._stream(), **kwargs)

    @overload
    def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    def export(  # noqa: E704
        self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | StringIO | Items | None:
        return export(self, *args, **kwargs)


class AsyncPipe(PyPipe):
    """An asynchronous PyPipe object"""

    def __init__(
        self,
        name: str | None = None,
        source: AsyncItems | Awaitable[Items] | Items | None = None,
        conf: Conf | None = None,
        *,
        assign: str | None = None,
        connections: int = 16,
        context: Context | None = None,
        field: str | None = None,
        func: Function | None = None,
        inputs: Inputs | None = None,
        mode: ExecutionMode | None = None,
        others: Iterable[str] | Iterable[Stream] | None = None,
        parallel: bool = False,
        skip_if: SkipIf | None = None,
        submodule: bool | None = False,
        test: bool | None = False,
        verbose: bool | None = False,
        **kwargs: object,
    ):
        super().__init__(
            name,
            source,
            assign=assign,
            conf=conf,
            context=context,
            field=field,
            func=func,
            inputs=inputs,
            mode=mode,
            others=others,
            parallel=parallel,
            skip_if=skip_if,
            submodule=submodule,
            test=test,
            verbose=verbose,
            **kwargs,
        )
        self.connections: int = connections
        self._aiter: AsyncGenerator[Item, None] | None = None

        if self.name:
            self.async_pipe: AsyncPipeParser = resolve_module(self.name, "async_pipe")
            self.pollable: bool = getattr(self.async_pipe, "pollable")  # noqa: B009
            self.loopable: bool = getattr(self.async_pipe, "loopable")  # noqa: B009
            self.mapify: bool = self.loopable
        else:
            self.async_pipe = lambda source, **_: async_return(source)
            self.pollable = self.loopable = self.mapify = False

    def __getattr__(self, name: str) -> "AsyncPipe":
        if name.startswith("_"):
            raise AttributeError(name)

        return self._chain(name)

    def __aiter__(self) -> AsyncStream:
        if self._aiter is None:
            self._aiter = self._stream()

        return self._aiter

    async def __anext__(self) -> Item:
        if self._aiter is None:
            self._aiter = self._stream()

        return await anext(self._aiter)

    def __await__(self) -> Generator[Any, None, Stream]:
        return self._await_stream().__await__()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> bool:
        await self.aclose()
        return False

    async def aclose(self) -> None:
        """Close the pipe: stop the underlying async generator (idempotent)."""
        if self._aiter is not None:
            await self._aiter.aclose()

        self._close()

    async def split(self, **kwargs: object) -> SplitterParserOutput:
        splits = await self._chain("split", **kwargs)
        return cast(SplitterParserOutput, splits)

    @overload
    async def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    async def export(  # noqa: E704
        self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    async def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | StringIO | Items | None:
        items = [item async for item in self]

        try:
            result = export(items, *args, **kwargs)
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing AsyncPipe attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result

    def _chain(self, name: str, **kwargs: object) -> "AsyncPipe":
        """
        Create the next async pipe stage, propagating runtime and execution
        settings and consuming this pipe's single execution (not restarting it).
        """
        self._require_usable("chain")
        skwargs = {
            "parallel": self.parallel,
            "context": self.context,
            "inputs": self.inputs,
            "connections": self.connections,
        }
        skwargs.update(kwargs)
        return AsyncPipe(name, source=self, **skwargs)

    async def _resolve_source(self) -> Items | None:
        """
        Materialize the source to a sync stream for the parser.

        A parent pipe (any ``AsyncIterable``) is drained through its memoized
        ``__aiter__`` so chaining wraps the *remaining* stream (mirrors sync
        ``source=self``); an ``Awaitable`` is awaited; a plain sync iterable is
        adapted to a ``Feed`` via ``async_iter`` and drained.
        """
        src = self.source

        if src is None:
            resolved = None
        elif isinstance(src, AsyncIterable):
            resolved = [item async for item in src]
        elif isawaitable(src):
            resolved = await src
        else:
            resolved = [item async for item in async_iter(src)]

        return resolved

    async def _stream(self) -> AsyncGenerator[Item, None]:
        self._begin()

        try:
            source = await self._resolve_source()
            async_pipeline = partial(self.async_pipe, **self.kwargs)

            if self.mapify and source is not None:
                mapped = await async_map(async_pipeline, source, self.connections)

                for stream in mapped:
                    for item in stream:
                        yield item
            else:
                result = await async_pipeline(source)

                for item in result:
                    yield item
        except BaseException:
            self._fail()
            raise
        finally:
            self._end()

    async def _await_stream(self) -> Stream:
        """Converts the AsyncIterator stream to an Awaitable"""
        return iter([item async for item in self])


class AsyncCollection(PyCollection):
    """An asynchronous PyCollection object"""

    def __init__(
        self,
        sources: Iterable[Mapping[str, str]],
        *,
        conf: Conf | None = None,
        workers: int | None = None,
        parallel: bool = False,
        connections: int = 16,
        **kwargs: object,
    ):
        super().__init__(
            sources, conf=conf, workers=workers, parallel=parallel, **kwargs
        )
        self.connections: int = connections
        self._aiter: AsyncGenerator[Item, None] | None = None

    def __aiter__(self) -> AsyncStream:
        if self._aiter is None:
            self._aiter = self._stream()

        return self._aiter

    async def __anext__(self) -> Item:
        if self._aiter is None:
            self._aiter = self._stream()

        return await anext(self._aiter)

    def __await__(self) -> Generator[Any, None, Stream]:
        return self._await_stream().__await__()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> bool:
        await self.aclose()
        return False

    async def aclose(self) -> None:
        """Close the collection: stop the underlying async generator (idempotent)."""
        if self._aiter is not None:
            await self._aiter.aclose()

        self._close()

    def async_pipe(self, **kwargs: Any) -> "AsyncPipe":
        """Return an AsyncPipe primed with the source feed"""
        return AsyncPipe(source=self, **kwargs)

    @overload
    async def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    async def export(  # noqa: E704
        self, _type: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    async def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | StringIO | Items | None:
        items = [item async for item in self]
        return export(items, *args, **kwargs)

    async def _stream(self) -> AsyncGenerator[Item, None]:
        """Fetch all source urls"""
        self._begin()

        try:
            zargs = zip(self.sources, repeat(self.conf))
            mapped = await async_map(afetch_source, zargs, self.connections)

            for stream in mapped:
                for item in stream:
                    yield item
        except BaseException:
            self._fail()
            raise
        finally:
            self._end()

    async def _await_stream(self) -> Stream:
        """Converts the AsyncIterator stream to an Awaitable"""
        return iter([item async for item in self])


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
