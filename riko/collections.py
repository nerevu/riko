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
        >>> from riko import run, issync
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
        ...     s = await AsyncCollection(sources, ordered=True)
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
    Callable,
    Generator,
    Iterable,
    Mapping,
)
from contextlib import aclosing
from enum import StrEnum
from functools import partial
from inspect import isawaitable
from io import StringIO
from itertools import chain, repeat
from logging import Logger
from multiprocessing import Pool as CPUPool
from multiprocessing import cpu_count
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import Pool as CPUPoolType
from multiprocessing.pool import ThreadPool as ThreadPoolType
from operator import length_hint
from typing import Any, Literal, Protocol, Self, TypeGuard, cast, overload

import pygogo as gogo

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

from riko import DEF_CONNECTION_COUNT
from riko._iterutils import listize
from riko._pubsub import sync_hub
from riko.bado import async_return
from riko.bado.itertools import (
    async_iter,
    async_map,
    async_map_ordered_stream,
    async_map_stream,
    async_merge,
)
from riko.compile import resolve_module
from riko.context import Context, ExecutionMode, parse_context
from riko.exceptions import PipelineStateError
from riko.ext.names import ModuleNameLike, normalize_module_name
from riko.types.general import (
    AsyncPipeParser,
    AsyncSource,
    AsyncStream,
    Conf,
    ConversionFunc,
    Feed,
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

type AnyPool = ThreadPoolType | CPUPoolType
type PoolFactory = Callable[..., AnyPool]

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Executor",
    "SyncCollection",
    "SyncPipe",
    "export",
    "list_targets",
]


class TemplatePipe(Protocol):
    name: str

    def _prime(self, source: Items) -> Self: ...  # noqa: E704


def _is_pipe_spec(obj: object) -> TypeGuard[tuple[str, Conf]]:
    return (
        isinstance(obj, tuple)
        and len(obj) == 2
        and isinstance(obj[0], str)
        and isinstance(obj[1], Mapping)
    )


def _is_source(obj: object) -> TypeGuard[Items]:
    """
    A stream of items on the left of ``|`` — any iterable that isn't a bare
    string/bytes or a single ``Mapping`` item.
    """
    return isinstance(obj, Iterable) and not isinstance(obj, str | bytes | Mapping)


def _is_template(obj: object) -> TypeGuard[TemplatePipe]:
    """A named, source-less, not-yet-run pipe — safe to rebind onto a source."""
    return (
        isinstance(obj, PyPipe)
        and bool(obj.name)
        and obj.source is None
        and obj._state is PipeState.NEW
    )


class PoolScope(StrEnum):
    PIPE = "pipe"
    PIPELINE = "pipeline"


class PipeState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    EXHAUSTED = "exhausted"
    CLOSED = "closed"
    FAILED = "failed"


class Executor(StrEnum):
    INLINE = "inline"
    THREAD = "thread"
    PROCESS = "process"


_POOLS: dict[Executor, PoolFactory] = {
    Executor.THREAD: ThreadPool,
    Executor.PROCESS: CPUPool,
}


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


def _settle_iter(current: Stream | None) -> Stream:
    """
    Close *current* if it is a live generator, else install a spent iterator.

    Called on close/terminate so a pipe or collection that is shut down before it
    ever iterates re-iterates as an empty stream (matching the spent-generator
    semantics of one that ran first) instead of building and executing a fresh
    ``_stream()`` on the next accessor call.
    """
    if current is not None:
        if (close := getattr(current, "close", None)) is not None:
            close()

        result = current
    else:
        result = iter(())

    return result


async def _spent_aiter() -> AsyncGenerator[Item, None]:
    """An exhausted async generator; the async counterpart to ``iter(())``."""
    return
    yield  # pragma: no cover


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
    test = takes input values from default (skips the console prompt)
    inputs = a dictionary of values that overrides the defaults
        e.g. {'name one': 'test value1'}
    """

    def __init__(
        self,
        name: ModuleNameLike | None = None,
        source: AsyncSource | None = None,
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
        self.name: str | None = normalize_module_name(name)
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
        )
        self.inputs: Inputs = self.context.inputs
        self.verbose: bool = bool(verbose)
        self.test: bool = bool(test)
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

    def _definitional_kwargs(self) -> dict[str, object]:
        """
        Module-behavior kwargs (``field``/``assign``/``emit``/…), excluding runtime
        settings carried separately (``conf``/``context``/ ``inputs``/``mode``). Used
        to rebind a source-less template onto a new source while preserving what the
        pipe *does*.
        """
        skip = {"conf", "context", "inputs", "mode"}
        return {k: v for k, v in self.kwargs.items() if k not in skip and v is not None}


class SyncPipe(PyPipe):
    """A synchronous Pipe object"""

    def __init__(
        self,
        name: ModuleNameLike | None = None,
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

        if parallel:
            self.executor = Executor.THREAD if self.threads else Executor.PROCESS
        else:
            self.executor = Executor.INLINE

        self.pool_scope: PoolScope = pool_scope
        self.ordered = ordered
        self._iter: Stream | None = None
        self._mapped: Iterable[Stream] | None = None
        self._in_context: bool = False
        self._terminal: bool = True
        self.source: Items = cast(Items, self.source)

        self.map: Callable[..., Iterable[Stream]]

        if pool_scope not in {"pipe", "pipeline"}:
            raise ValueError("pool_scope must be either 'pipe' or 'pipeline'")

        if pool and _pool_handle:
            raise TypeError("pool and _pool_handle cannot both be provided")
        elif pool:
            self._pool_handle: _PoolHandle | None = _PoolHandle(pool, owned=False)
        else:
            self._pool_handle = _pool_handle

        if self.name:
            self._pipe: SyncPipeParser = resolve_module(self.name, "pipe")
            self.pollable: bool = getattr(self._pipe, "pollable")  # noqa: B009
            self.loopable: bool = getattr(self._pipe, "loopable")  # noqa: B009
            self.mapify: bool = self.loopable and self.source is not None
            self.parallelize: bool = self.parallel and self.mapify
        else:
            self._pipe = lambda source, **_: source
            self.pollable = self.loopable = self.mapify = self.parallelize = False

        if self.parallelize:
            length = length_hint(self.source)
            def_pool = _POOLS.get(self.executor)
            self.workers: int | None = workers or get_worker_cnt(length, self.threads)
            self.chunksize: int = chunksize or get_chunksize(length, self.workers)

            if not self._pool_handle:
                new_pool = def_pool(self.workers)
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

    def _chain(self, name: ModuleNameLike, **kwargs: object) -> "SyncPipe":
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
            "chunksize": self.chunksize,
            "context": self.context,
            "inputs": self.inputs,
            "parallel": self.parallel,
            "pool_scope": next_scope,
            "threads": self.threads,
            "workers": self.workers,
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

    def __or__(self, other: object) -> "SyncPipe":
        """
        Chain the next pipe via ``|``.

        The right side may be a module name, a ``(name, conf)`` pair, or a
        source-less ``SyncPipe`` template (``pipe | SyncPipe("sort", ...)``).

        Examples:
            >>> flow = SyncPipe('itembuilder')
            >>> piped = flow | 'hash'
            >>> piped.name, piped.source is flow
            ('hash', True)
            >>> piped = SyncPipe('itembuilder') | ('sort', {'combine': 'a'})
            >>> piped.name, piped.conf
            ('sort', {'combine': 'a'})
            >>> template = SyncPipe('sort', conf={'combine': 'a'})
            >>> piped = SyncPipe('itembuilder') | template
            >>> piped.name, piped.conf, piped.source is flow
            ('sort', {'combine': 'a'}, False)

        """
        if isinstance(other, str):
            chained = self._chain(other)
        elif _is_pipe_spec(other):
            name, conf = other
            chained = self._chain(name, conf=conf)
        elif _is_template(other) and isinstance(other, SyncPipe):
            name = other.name
            chained = self._chain(name, conf=other.conf, **other._definitional_kwargs())
        else:
            chained = NotImplemented

        return chained

    def __ror__(self, other: object) -> "SyncPipe":
        """
        Seed a stream on the left of ``|``: ``items | SyncPipe("filter")``.

        Examples:
            >>> items = [{'x': 1}, {'x': 2}]
            >>> piped = items | SyncPipe('sort')
            >>> piped.name, list(piped.source) == items
            ('sort', True)

        """
        if _is_template(self) and _is_source(other):
            primed = self._prime(other)
        else:
            primed = NotImplemented

        return primed

    def _prime(self, source: Items) -> "SyncPipe":
        """
        Rebind a source-less pipe template onto a new source, returning a fresh
        pipe instance. The original template is left intact.
        """
        self._require_usable("chain")
        skwargs = {
            "chunksize": self.chunksize,
            "conf": self.conf,
            "context": self.context,
            "inputs": self.inputs,
            "ordered": self.ordered,
            "parallel": self.parallel,
            "pool_scope": self.pool_scope,
            "threads": self.threads,
            "workers": self.workers,
        }
        skwargs.update(self._definitional_kwargs())
        return SyncPipe(self.name, source=source, **skwargs)

    def pipe(self, name: ModuleNameLike, **kwargs: Any) -> "SyncPipe":
        """
        Chain the next pipe by name (the method form of ``pipe | name``).

        Accepts arbitrary pipe kwargs (``conf``/``field``/``assign``/…) that the
        terse ``|`` form can't. Runtime settings propagate via ``_chain``.

        Examples:
            >>> flow = SyncPipe('itembuilder')
            >>> chained = flow.pipe('hash')
            >>> chained.name, chained.source is flow
            ('hash', True)

        """
        return self._chain(name, **kwargs)

    def _release_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.close()

    def _terminate_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.terminate()

    def close(self) -> None:
        self._iter = _settle_iter(self._iter)
        self._release_pool()
        self._close()

    def terminate(self) -> None:
        self._iter = _settle_iter(self._iter)
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
        elif self.pool_scope == PoolScope.PIPE:
            result = True
        else:
            result = self._terminal

        return result

    def _stream(self) -> Generator[Item, None, None]:
        if self.name == "send":
            self.kwargs.setdefault("ids", {})

        self._begin()
        pipeline = partial(self._pipe, **self.kwargs)
        completed = False

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
        except GeneratorExit:
            # A graceful close is "no more items on this channel", so a bound
            # sender still signals DONE to its receivers; a real failure below
            # must not, else a failed sender looks successfully complete.
            completed = True
            raise
        except BaseException:
            self._fail()

            if self._release_pool_after_iteration():
                self._terminate_pool()

            raise
        else:
            completed = True
        finally:
            if self._release_pool_after_iteration():
                self._release_pool()

            self._end()

            if completed:
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

        if parallel:
            self.executor = Executor.THREAD if self.threads else Executor.PROCESS
        else:
            self.executor = Executor.INLINE

        self.ordered: bool = bool(ordered)
        self._iter: Stream | None = None
        self.map: Callable[..., Iterable[Stream]]
        self._in_context: bool = False
        self._pool_handle: _PoolHandle | None = (
            _PoolHandle(pool, owned=False) if pool else None
        )

        if self.parallel:
            self.chunksize: int = get_chunksize(self.length, self.workers)
            def_pool = _POOLS.get(self.executor)

            if not self._pool_handle:
                new_pool = def_pool(self.workers)
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
        self._iter = _settle_iter(self._iter)
        self._release_pool()
        self._close()

    def terminate(self) -> None:
        self._iter = _settle_iter(self._iter)
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

    def pipe(self, name: ModuleNameLike | None = None, **kwargs: Any) -> "SyncPipe":
        """
        Chain the next pipe by name: ``pipe.pipe("filter", conf=...)``.

        Examples:
            >>> flow = SyncPipe('itembuilder')
            >>> chained = flow.pipe('hash')
            >>> chained.name, chained.source is flow
            ('hash', True)

        """
        self._require_usable("chain")
        return SyncPipe(name, source=self, **kwargs)

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
    """
    An asynchronous PyPipe object.

    Note — eager-concurrent execution under *partial* consumption:
        A mapping stage runs its items concurrently, so *partially* consuming an
        ``AsyncPipe`` (``anext``, an early ``break``, or a downstream
        ``count="first"``/``truncate``) may run that stage's function for items
        you never yield — unlike ``SyncPipe``, which is lazy and sequential and
        runs it only for consumed items. Fully draining the pipe yields the
        *same* result on both engines; only a stage function's *side effects*
        under partial consumption differ.

        This matters only when a stage has side effects (e.g. ``send``, an
        external write). If so, bound the work at the stage instead of the
        consumer — pass ``count``/``truncate`` to the stage, or fully drain — so
        it isn't run for un-yielded items. ``parallel=True`` *bounds* the
        over-run to the in-flight window but does not eliminate it (a worker
        prefetches the next item).
    """

    def __init__(
        self,
        name: ModuleNameLike | None = None,
        source: AsyncSource | None = None,
        conf: Conf | None = None,
        *,
        assign: str | None = None,
        connections: int = DEF_CONNECTION_COUNT,
        context: Context | None = None,
        field: str | None = None,
        func: Function | None = None,
        inputs: Inputs | None = None,
        mode: ExecutionMode | None = None,
        ordered: bool = False,
        others: Iterable[str] | Iterable[Stream] | None = None,
        parallel: bool = False,
        prefetch: int = 0,
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
        if connections < 1:
            raise ValueError("limit must be at least 1")

        self.connections: int = connections
        self.ordered: bool = ordered
        self.prefetch: int = prefetch
        self._aiter: AsyncGenerator[Item, None] | None = None

        if self.name:
            self._async_pipe: AsyncPipeParser = resolve_module(self.name, "async_pipe")
            self.pollable: bool = getattr(self._async_pipe, "pollable")  # noqa: B009
            self.loopable: bool = getattr(self._async_pipe, "loopable")  # noqa: B009
            self.mapify: bool = self.loopable
        else:
            self._async_pipe = lambda source, **_: async_return(source)
            self.pollable = self.loopable = self.mapify = False

    def __getattr__(self, name: str) -> "AsyncPipe":
        if name.startswith("_"):
            raise AttributeError(name)

        return self._chain(name)

    def __or__(self, other: object) -> "AsyncPipe":
        """
        Chain the next pipe via ``|``.

        The right side may be a module name, a ``(name, conf)`` pair, or a
        source-less ``AsyncPipe`` template (``pipe | AsyncPipe("sort", ...)``).

        Examples:
            >>> flow = AsyncPipe('itembuilder')
            >>> piped = flow | 'hash'
            >>> piped.name, piped.source is flow
            ('hash', True)
            >>> piped = AsyncPipe('itembuilder') | ('sort', {'combine': 'a'})
            >>> piped.name, piped.conf
            ('sort', {'combine': 'a'})
            >>> template = AsyncPipe('sort', conf={'combine': 'a'})
            >>> piped = AsyncPipe('itembuilder') | template
            >>> piped.name, piped.conf, piped.source is flow
            ('sort', {'combine': 'a'}, False)

        """
        if isinstance(other, str):
            chained = self._chain(other)
        elif _is_pipe_spec(other):
            name, conf = other
            chained = self._chain(name, conf=conf)
        elif _is_template(other) and isinstance(other, AsyncPipe):
            name = other.name
            chained = self._chain(name, conf=other.conf, **other._definitional_kwargs())
        else:
            chained = NotImplemented

        return chained

    def __ror__(self, other: object) -> "AsyncPipe":
        """
        Seed a stream on the left of ``|``: ``items | AsyncPipe("filter")``.

        Examples:
            >>> items = [{'x': 1}, {'x': 2}]
            >>> piped = items | AsyncPipe('sort')
            >>> piped.name, list(piped.source) == items
            ('sort', True)

        """
        if _is_template(self) and _is_source(other):
            primed = self._prime(other)
        else:
            primed = NotImplemented

        return primed

    def _prime(self, source: Items) -> "AsyncPipe":
        """
        Rebind a source-less pipe template onto a new source, returning a fresh
        pipe instance. The original template is left intact.
        """
        self._require_usable("chain")
        skwargs = {
            "conf": self.conf,
            "connections": self.connections,
            "context": self.context,
            "inputs": self.inputs,
            "ordered": self.ordered,
            "parallel": self.parallel,
            "prefetch": self.prefetch,
        }
        skwargs.update(self._definitional_kwargs())
        return AsyncPipe(self.name, source=source, **skwargs)

    def async_pipe(self, name: ModuleNameLike, **kwargs: Any) -> "AsyncPipe":
        """Chain the next pipe by name (the method form of ``pipe | name``)."""
        return self._chain(name, **kwargs)

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
        if self._aiter is None:
            self._aiter = _spent_aiter()
        else:
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

    def _chain(self, name: ModuleNameLike, **kwargs: object) -> "AsyncPipe":
        """
        Create the next async pipe stage, propagating runtime and execution
        settings and consuming this pipe's single execution (not restarting it).
        """
        self._require_usable("chain")
        skwargs = {
            "connections": self.connections,
            "context": self.context,
            "inputs": self.inputs,
            "ordered": self.ordered,
            "parallel": self.parallel,
            "prefetch": self.prefetch,
        }
        skwargs.update(kwargs)
        return AsyncPipe(name, source=self, **skwargs)

    async def _normalize_source(self) -> Feed | None:
        """
        Normalize the configured source into a lazy async iterable.

        ``None`` remains ``None`` to distinguish a source-less stage from an
        upstream source that happens to be empty.
        """
        source = self.source

        if source is None:
            resolved = None
        else:
            resolved = await source if isawaitable(source) else source

            if isinstance(resolved, AsyncIterable):
                resolved = aiter(resolved)
            else:
                resolved = async_iter(resolved)

        return resolved

    async def _materialize_legacy_source(self, feed: Feed | None) -> Items | None:
        """
        Drain a Feed into a list for a non-Feed-native module parser.

        This is the **explicit legacy-parser boundary**, not the default way
        stages communicate. Today's module parsers still require synchronous
        ``Items`` rather than a ``Feed``, so a non-parallel async stage buffers
        its whole upstream here: everything *before* this point streams lazily,
        everything *after* it has been materialized. The bounded/parallel path
        (``_stream``) is the only fully-lazy end-to-end route; per-module opt-in
        to Feed-native parsers (ROADMAP §4/§8) will shrink this boundary.
        """
        return None if feed is None else [item async for item in feed]

    async def _stream(self) -> AsyncGenerator[Item, None]:
        self._begin()
        async_pipeline = partial(self._async_pipe, **self.kwargs)
        bounded = self.mapify and self.parallel

        try:
            feed = await self._normalize_source()

            if bounded and feed is not None:
                limit = self.connections
                map_stream = (
                    async_map_ordered_stream if self.ordered else async_map_stream
                )
                mapped = map_stream(
                    async_pipeline, feed, limit=limit, buffer=self.prefetch
                )

                # ``aclosing`` tears the inner stream (and its task group) down in
                # *this* task on any exit, so an early close doesn't leak it to a
                # cross-task GC finalizer (which trips anyio's cancel-scope guard).
                # Closing the as-complete stream mid-flight re-raises its task
                # group's ``GeneratorExit`` as a one-member group; that is the
                # expected close signal, so unwrap it back into a clean close and
                # let anything genuinely unexpected propagate.
                try:
                    async with aclosing(mapped):
                        async for stream in mapped:
                            for item in stream:
                                yield item
                except BaseExceptionGroup as eg:
                    if eg.split(GeneratorExit)[1] is not None:
                        raise

                    raise GeneratorExit from None
            else:
                source = await self._materialize_legacy_source(feed)

                if self.mapify and source is not None:
                    mapped = await async_map(async_pipeline, source, self.connections)

                    for stream in mapped:
                        for item in stream:
                            yield item
                else:
                    result = await async_pipeline(source)

                    if isinstance(result, AsyncIterable):
                        async for item in result:
                            yield item
                    else:
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
        connections: int = DEF_CONNECTION_COUNT,
        ordered: bool = False,
        prefetch: int = 0,
        **kwargs: object,
    ):
        super().__init__(
            sources, conf=conf, workers=workers, parallel=parallel, **kwargs
        )
        if connections < 1:
            raise ValueError("limit must be at least 1")

        self.connections: int = connections
        self.ordered: bool = ordered
        self.prefetch: int = prefetch
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
        if self._aiter is None:
            self._aiter = _spent_aiter()
        else:
            await self._aiter.aclose()

        self._close()

    def async_pipe(
        self, name: ModuleNameLike | None = None, **kwargs: Any
    ) -> "AsyncPipe":
        """Chain the next pipe by name: ``pipe.async_pipe("filter", conf=...)``."""
        return AsyncPipe(name, source=self, **kwargs)

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
            if self.ordered:
                # Explicit source-materialization compatibility mode: each source
                # is fetched (concurrently, up to `connections`) and its records
                # yielded in source order; records do not interleave across sources.
                zargs = zip(self.sources, repeat(self.conf))
                mapped = async_map_ordered_stream(
                    afetch_source_eager,
                    zargs,
                    limit=self.connections,
                    buffer=self.prefetch,
                )

                async for stream in mapped:
                    for item in stream:
                        yield item
            else:
                # Incremental merge: each source is a lazy Feed and records
                # interleave across sources as they arrive (bounded by
                # `connections`), never materializing a whole source.
                feeds = (afetch_source((src, self.conf)) for src in self.sources)
                merged = async_merge(
                    feeds, limit=self.connections, buffer=self.prefetch
                )

                try:
                    async with aclosing(merged):
                        async for item in merged:
                            yield item
                except BaseExceptionGroup as eg:
                    if eg.split(GeneratorExit)[1] is not None:
                        raise

                    raise GeneratorExit from None
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


def _fetch_source[T: SyncPipe | AsyncPipe](
    args: tuple[Mapping[str, str], Conf], pipe: type[T]
) -> T:
    source, _conf = args
    conf = {**_conf, **source}
    pipe_name = str(source.get("type", "fetch"))
    return pipe(pipe_name, conf=cast(Conf, conf))


def fetch_source(
    args: tuple[Mapping[str, str], Conf], pipe: type[SyncPipe] = SyncPipe
) -> Stream:
    return iter(_fetch_source(args, pipe))


def afetch_source(
    args: tuple[Mapping[str, str], Conf], pipe: type[AsyncPipe] = AsyncPipe
) -> AsyncStream:
    """
    Return a lazy, unstarted async feed for one collection source.

    Unlike ``afetch_source_eager`` (which materializing the whole source), this
    hands back the source's async iterator so ``async_merge`` can stream its records
    incrementally.
    """
    return aiter(_fetch_source(args, pipe))


async def afetch_source_eager(
    args: tuple[Mapping[str, str], Conf], pipe: type[AsyncPipe] = AsyncPipe
) -> Stream:
    return await _fetch_source(args, pipe)
