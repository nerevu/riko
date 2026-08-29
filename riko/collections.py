# vim: sw=4:ts=4:expandtab
"""
Provides functions for creating (a)synchronous riko flows and streams.

Examples:
    sync usage::

        >>> from riko import get_path, SyncPipe
        >>>
        >>> fconf = {"url": get_path("gigs.json"), "path": "value.items"}
        >>> str_conf = {"delimiter": "<br>"}
        >>> str_kwargs = {"field": "description", "emit": True}
        >>> sort_conf = {"rule": {"field": "title"}}
        >>>
        >>> list(SyncPipe("fetchdata", conf=fconf)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ... )
        [{'count': 169}]
        >>> list(SyncPipe("fetchdata", conf=fconf, parallel=True)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ... )
        [{'count': 169}]
        >>> list(SyncPipe("fetchdata", conf=fconf, parallel=True, threads=False)
        ...     .sort(conf=sort_conf)
        ...     .tokenizer(conf=str_conf, **str_kwargs)
        ...     .count()
        ... )
        [{'count': 169}]
        >>> fconf["type"] = "fetchdata"
        >>> sources = [{"url": get_path("feed.xml")}, fconf]
        >>> stream = SyncCollection(sources)
        >>> next(stream)["title"]
        'Donations'
        >>> len(list(stream))
        55
        >>> len(list(SyncCollection(sources, parallel=True)))
        56

    async usage::

        >>> from riko import AsyncPipe, AsyncCollection, get_path, run, issync
        >>>
        >>> fconf = {"url": get_path("gigs.json"), "path": "value.items"}
        >>> str_conf = {"delimiter": "<br>"}
        >>> str_kwargs = {"field": "description", "emit": True}
        >>> sort_conf = {"rule": {"field": "title"}}
        >>>
        >>> async def main():
        ...     d = await (AsyncPipe("fetchdata", conf=fconf)
        ...         .sort(conf=sort_conf)
        ...         .tokenizer(conf=str_conf, **str_kwargs)
        ...         .count()
        ...     )
        ...
        ...     print(list(d))
        >>>
        >>> if issync:
        ...     [{"count": 169}]
        ... else:
        ...     run(main)
        [{'count': 169}]
        >>> async def main():
        ...     fconf["type"] = "fetchdata"
        ...     sources = [{"url": get_path("feed.xml")}, fconf]
        ...     s = await AsyncCollection(sources, ordered=True)
        ...     d = list(s)
        ...     print(d[0]["title"])
        ...     print(len(d))
        >>>
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
from typing import Any, Literal, Protocol, Self, TextIO, TypeGuard, cast, overload

import pygogo as gogo

from riko._pubsub._types import ReceiveFunc
from riko.types._collections import Inputs
from riko.types._options import SkipIf
from riko.types._scalars import BasicValue
from riko.types.modules import Conf, ReceiveConf

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

from riko._constants import DEF_CONNECTION_COUNT
from riko._iterutils import listize
from riko._pubsub import sync_hub
from riko.bado._util import async_return
from riko.bado.itertools import (
    async_iter,
    async_map,
    async_map_ordered_stream,
    async_map_stream,
    async_merge,
)
from riko.context import Context, ExecutionMode, parse_context
from riko.exceptions import PipelineStateError
from riko.ext._resolver import pipe_resolver
from riko.ext.names import normalize_module_name
from riko.types._names import ModuleNameLike, TargetLike, TargetName
from riko.types._streams import AsyncSource, AsyncStream, Feed, Item, Items, Stream
from riko.types._wrappers import (
    AsyncPipeParser,
    ConversionFunc,
    ParserOutput,
    SplitterParserOutput,
    SyncPipeParser,
)

type AnyPool = ThreadPoolType | CPUPoolType
type PoolFactory = Callable[..., AnyPool]

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Executor",
    "SyncCollection",
    "SyncPipe",
    "Targets",
    "export",
    "list_targets",
]


class TemplatePipe(Protocol):
    """A source-less pipe that can be rebound onto a stream."""

    name: str

    def _prime(self, source: Items) -> Self: ...  # noqa: E704


def _is_pipe_spec(obj: object) -> TypeGuard[tuple[str, Conf]]:
    """A ``(name, conf)`` pair on the right of ``|``."""
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


class Targets(TargetName):
    """A type-safe ``export`` target."""

    CSV = "csv"
    GEOJSON = "geojson"
    JSON = "json"
    LIST = "list"
    OFX = "ofx"
    QIF = "qif"
    TUPLE = "tuple"


class PoolScope(StrEnum):
    """
    How long a worker pool outlives the pipe that created it.

    ``PIPELINE`` shares one pool across a whole chain and releases it when the
    terminal pipe finishes; ``PIPE`` gives each pipe its own and releases it as
    soon as that pipe is done.
    """

    PIPE = "pipe"
    PIPELINE = "pipeline"


class PipeState(StrEnum):
    """
    The lifecycle state of a pipe or collection.

    A pipe is one-shot: it advances ``NEW`` → ``RUNNING`` → one of the three
    terminal states and never restarts. ``EXHAUSTED`` means the stream ran to
    completion, ``CLOSED`` that it was released early, and ``FAILED`` that it
    raised. Re-iterating a terminal instance yields nothing. Chaining onto a
    ``CLOSED`` or ``FAILED`` one raises ``PipelineStateError``.
    """

    NEW = "new"
    RUNNING = "running"
    EXHAUSTED = "exhausted"
    CLOSED = "closed"
    FAILED = "failed"


class Executor(StrEnum):
    """
    Where a pipe's per-item work runs.

    Derived from ``parallel``/``threads`` rather than set directly: ``INLINE``
    when ``parallel`` is off, otherwise ``THREAD`` or ``PROCESS``.
    """

    INLINE = "inline"
    THREAD = "thread"
    PROCESS = "process"


_POOLS: dict[Executor, PoolFactory] = {
    Executor.THREAD: ThreadPool,
    Executor.PROCESS: CPUPool,
}


class _Lifecycle:
    """
    Tracks one-shot execution state for pipes and collections.

    Re-iterating a completed instance yields no items. Chaining onto a
    ``CLOSED`` or ``FAILED`` instance raises ``PipelineStateError``.
    """

    _state: PipeState = PipeState.NEW

    @property
    def state(self) -> PipeState:
        """The current lifecycle state."""
        return self._state

    @property
    def closed(self) -> bool:
        """Whether the instance was closed or terminated before exhausting."""
        return self._state is PipeState.CLOSED

    @property
    def exhausted(self) -> bool:
        """Whether the stream ran to completion."""
        return self._state is PipeState.EXHAUSTED

    @property
    def failed(self) -> bool:
        """Whether the stream raised while being consumed."""
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


class _SendDispatcher:
    """
    Binds ``SyncPipe.publish`` to a class or instance form.

    When called as a class method, ``publish`` seeds a new publisher from a source. When
    called on an instance, it chains ``publish`` into the pipeline. Either way the items
    pass through unchanged, so a publisher can sit mid-stream as well as terminate one.
    """

    def __get__(
        self, obj: "SyncPipe | None", cls: "type[SyncPipe] | None" = None
    ) -> "partial[SyncPipe]":
        if cls is not None and obj is None:
            method = partial(self.cls_send, cls)
        elif obj is None:
            raise TypeError("SyncPipe.publish must be called on a class or instance.")
        else:
            method = partial(self.inst_send, obj)

        return method

    def cls_send(self, cls: "type[SyncPipe]", source: Items, *names: str) -> "SyncPipe":
        """
        Returns a publisher that pushes source items to each named subscriber.

        Raises:
            TypeError: If no subscriber name is given.

        Examples:
            >>> items = [{"title": "Gravity paper"}, {"title": "riko 4.0"}]
            >>> subscriber = SyncPipe.subscribe("papers")
            >>> _ = list(SyncPipe.publish(items, "papers"))
            >>> [item["title"] for item in subscriber]
            ['Gravity paper', 'riko 4.0']

        """
        return cls("send", source, others=list(names))

    def inst_send(self, obj: "SyncPipe", *names: str) -> "SyncPipe":
        """
        Returns a publisher that pushes a pipeline's items to each named subscriber.

        Raises:
            TypeError: If no subscriber name is given.

        Examples:
            >>> items = [{"title": "Gravity paper"}, {"title": "riko 4.0"}]
            >>> subscriber = SyncPipe.subscribe("papers")
            >>> _ = list(SyncPipe(source=items).publish("papers"))
            >>> [item["title"] for item in subscriber]
            ['Gravity paper', 'riko 4.0']

        """
        return obj._chain("send", others=list(names))


def _settle_iter(current: Stream | None) -> Stream:
    """Closes a live iterator or returns an exhausted iterator."""
    if current is None:
        result = iter(())
    else:
        if (close := getattr(current, "close", None)) is not None:
            close()

        result = current

    return result


async def _spent_aiter() -> AsyncGenerator[Item, None]:
    """An exhausted async generator; the async counterpart to ``iter(())``."""
    return
    yield  # pragma: no cover


def records2ofx(items: Items, **_: object) -> Iterable[str]:
    """Serializes records as OFX. Registered only with the ``finance`` extra."""
    ofx = OFX(mapping)
    groups = ofx.gen_groups(items)
    trxns = ofx.gen_trxns(groups)
    cleaned_trxns = ofx.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(ofx.header(), ofx.gen_body(data), ofx.footer())


def records2qif(items: Items, **_: object) -> Iterable[str]:
    """Serializes records as QIF. Registered only with the ``finance`` extra."""
    qif = QIF(mapping)
    groups = qif.gen_groups(items)
    trxns = qif.gen_trxns(groups)
    cleaned_trxns = qif.clean_trxns(trxns)
    data = gen_data(cleaned_trxns)
    return chain(qif.gen_body(data), qif.footer())


CONVERSION_FUNCS: dict[TargetLike, ConversionFunc] = {
    # "array": cv.records2array,
    Targets.CSV: cv.records2csv,
    # "dataframe": cv.records2df,
    Targets.GEOJSON: cv.records2geojson,
    # 'ical': cv.records2ical,
    Targets.JSON: cv.records2json,
    # 'kml': cv.records2kml,
    Targets.LIST: lambda items, **_: list(items),
    Targets.TUPLE: lambda items, **_: tuple(items),
}

if OFX is not None:
    CONVERSION_FUNCS[Targets.OFX] = cast(ConversionFunc, records2ofx)
    CONVERSION_FUNCS[Targets.QIF] = cast(ConversionFunc, records2qif)


def list_targets() -> list[str]:
    """
    Returns every available ``export`` target, sorted.

    ``ofx`` and ``qif`` are present only with the ``finance`` extra installed.

    Examples:
        >>> targets = list_targets()
        >>> targets[:4]
        ['csv', 'geojson', 'json', 'list']

    """
    return sorted(map(str, CONVERSION_FUNCS))


@overload
def export(items: Items) -> list[Item]: ...  # noqa: E704
@overload
def export(items: Items, **kwargs: Any) -> list[Item]: ...  # noqa: E704
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, type_: Literal["list", Targets.LIST], **kwargs: Any
) -> list[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, type_: Literal["tuple", Targets.TUPLE], **kwargs: Any
) -> tuple[Item]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal[
        "csv", "json", "geojson", Targets.CSV, Targets.JSON, Targets.GEOJSON
    ],
    f: str,
    **kwargs: Any,
) -> int: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal[
        "csv", "json", "geojson", Targets.CSV, Targets.JSON, Targets.GEOJSON
    ],
    f: None = ...,
    **kwargs: Any,
) -> StringIO: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal["ofx", "qif", Targets.OFX, Targets.QIF],
    f: str,
    **kwargs: Any,
) -> int: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items,
    type_: Literal["ofx", "qif", Targets.OFX, Targets.QIF],
    f: None = ...,
    **kwargs: Any,
) -> Iterable[str]: ...
@overload  # noqa: E302
def export(  # noqa: E704
    items: Items, type_: TargetLike = ..., **kwargs: Any
) -> StringIO | Items | Iterable[str] | None: ...
def export(  # noqa: E302
    items: Items,
    type_: TargetLike = Targets.LIST,
    f: str | TextIO | None = None,
    **kwargs: Any,
) -> int | StringIO | Items | Iterable[str] | None:
    """
    Converts a stream to ``type_``, optionally writing it to ``f``.

    Args:
        items: The stream to convert.

        type_: An ``export`` target. ``list``/``tuple`` return the records
            themselves; the rest serialize.

        f: Destination path or file object. When given, the serialized output is
            written there and the byte count is returned instead.

        kwargs: Passed through to the underlying converter and writer.

    Returns:
        The records for ``list``/``tuple``, a ``StringIO`` for a serializing
        target, or the number of bytes written when ``f`` is given.

    Raises:
        ValueError: If ``type_`` is not a known target.

    Examples:
        >>> items = [{"x": 1}, {"x": 2}]
        >>>
        >>> export(items)
        [{'x': 1}, {'x': 2}]
        >>> export(items, "csv").getvalue().splitlines()
        ['x', '1', '2']

    """
    result = None

    if converter := CONVERSION_FUNCS.get(type_):
        if type_ in {Targets.LIST, Targets.TUPLE}:
            records = list(items)
        else:
            records = [dict(item) for item in items]

        _result = converter(records, **kwargs)

        if f:
            result = cast(int, io.write(f, _result, **kwargs))
        else:
            result = _result
    else:
        valid = ", ".join(CONVERSION_FUNCS)
        raise ValueError(f"Invalid export type {type_!r}. Must be one of: {valid}.")

    return result


class PyPipe(_Lifecycle):
    """
    One module invocation, bound to a name, a source, and its options.

    The engine-agnostic half of a pipe: it resolves the module name, merges
    call-time options into the kwargs the module parser receives, and tracks
    lifecycle state. ``SyncPipe`` and ``AsyncPipe`` add the execution model.

    Args:
        name: Module to run. A source pipe takes no ``source``.
        source: Upstream stream, or another pipe to chain onto.
        verbose: Whether to print debug output while running.
        test: Whether to use input defaults instead of prompting.
        inputs: Values that override the input defaults.

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
        func: Callable | None = None,
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
        self.name: str = normalize_module_name(name)
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
        func: Callable | None = None,
        inputs: Inputs | None = None,
        mode: ExecutionMode | None = None,
        others: Iterable[str] | Iterable[Stream] | None = None,
        skip_if: SkipIf | None = None,
        **kwargs: object,
    ) -> Self:
        """
        Merges call-time options into this pipe and returns it.

        Mutates in place rather than copying, which is what lets a chained
        ``.tokenizer(emit=True)`` resolve the module by attribute and then apply
        its options by call.
        """
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
        Returns module options used to rebind a pipe template.

        E.g., ``field``/``assign``/``emit``/…
        """
        skip = {"conf", "context", "inputs", "mode"}
        return {k: v for k, v in self.kwargs.items() if k not in skip and v is not None}


class SyncPipe(PyPipe):
    """
    A lazily evaluated, one-shot synchronous pipe.

    Chain by attribute (``.sort()``), by name (``.pipe("sort")``), or with
    ``|``; nothing runs until the result is iterated. Set ``parallel`` to map
    items across a worker pool, which ``pool_scope`` shares along the chain or
    confines to one pipe.

    Args:
        name: Module to run. A source pipe takes no ``source``.
        source: Upstream stream, or another pipe to chain onto.
        conf: The module's configuration.
        chunksize: Items dispatched per worker task when ``parallel``.
        ordered: Whether parallel results keep source order.
        parallel: Whether to map items across a worker pool.
        pool: An existing pool to borrow. Never closed by this pipe.
        pool_scope: Whether a pool spans the chain or just this pipe.
        threads: Whether a parallel pool uses threads rather than processes.
        workers: Pool size. Derived from the source length when unset.

    """

    publish: _SendDispatcher = _SendDispatcher()

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
        func: Callable | None = None,
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
            self._pipe: SyncPipeParser = pipe_resolver.resolve(self.name, "pipe")
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
        """The live worker pool, or ``None`` when inline or already released."""
        return self._pool_handle.pool if self._pool_handle else None

    def _chain(self, name: ModuleNameLike, **kwargs: object) -> "SyncPipe":
        """
        Returns the next pipe with the current runtime settings.

        Examples:
            >>> conf = {"key": "a", "value": "b"}
            >>> flow = SyncPipe("itembuilder", conf=conf, inputs={"x": "1"})
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
        """
        Chains any module by attribute, so ``.sort()`` runs the sort pipe.

        Every unknown non-underscore attribute is treated as a module name, so a
        typo surfaces as a module-resolution failure rather than
        ``AttributeError``. Mapping names are excluded to keep a pipe from
        looking dict-like to duck-typed callers.
        """
        if name.startswith("_") or name in {"keys", "values", "items", "get"}:
            raise AttributeError(name)

        return self._chain(name)

    def __or__(self, other: object) -> "SyncPipe":
        """
        Chains a module name, config pair, or pipe template using ``|``.

        Examples:
            >>> flow = SyncPipe("itembuilder")
            >>> piped = flow | "hash"
            >>> piped.name, piped.source is flow
            ('hash', True)
            >>> piped = SyncPipe("itembuilder") | ("sort", {"combine": "a"})
            >>> piped.name, piped.conf
            ('sort', {'combine': 'a'})
            >>> template = SyncPipe("sort", conf={"combine": "a"})
            >>> piped = SyncPipe("itembuilder") | template
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
        Seeds a stream on the left of ``|``.

        Examples:
            >>> items = [{"x": 1}, {"x": 2}]
            >>> piped = items | SyncPipe("sort")
            >>> piped.name, list(piped.source) == items
            ('sort', True)

        """
        if _is_template(self) and _is_source(other):
            primed = self._prime(other)
        else:
            primed = NotImplemented

        return primed

    def _prime(self, source: Items) -> "SyncPipe":
        """Returns a copy of this pipe template bound to ``source``."""
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
        Chains the next pipe by name.

        Examples:
            >>> flow = SyncPipe("itembuilder")
            >>> chained = flow.pipe("hash")
            >>> chained.name, chained.source is flow
            ('hash', True)

        """
        return self._chain(name, **kwargs)

    @classmethod
    def subscribe(
        cls,
        name: str,
        func: ReceiveFunc | None = None,
        wait: float | None = None,
        maxlen: int | None = None,
        assign: str | None = None,
        context: Context | None = None,
        inputs: dict[str, Any] | None = None,
        skip_if: Callable[[Item], bool] | None = None,
        test: bool | None = None,
        verbose: bool | None = None,
        **kwargs: object,
    ) -> "SyncPipe":
        """
        Returns a subscriber bound to a named channel.

        Registers the subscriber. A publisher may publish to ``name`` before the
        subscriber is drained and no priming call is needed. Draining is non-blocking:
        the subscriber yields whatever the channel holds, then stops. It never emits a
        ``StreamState`` marker, so the caller has nothing to filter out.

        Nothing published before ``subscribe`` is replayed; buffering starts here.

        Args:
            name: Subscriber the publisher sends to.

            func: Applied to each received item. The subscriber yields its return
                value, so a ``func`` returning ``None`` yields ``None``.

            wait: Seconds to sleep between polls. Applies only while a drain
                blocks, which it currently never does.

            maxlen: Queue capacity. The oldest item is dropped with a warning
                once it is full (default: unbounded).

            **kwargs: Passed to ``func``. Only the ones it names reach it, or
                all of them if it accepts ``**kwargs``. ``conf``, ``assign``,
                and ``stream`` are reserved and never forwarded.

        Returns:
            A one-shot pipe over the channel. Draining it a second time yields
            nothing; subscribe again for another pass.

        Examples:
            >>> items = [{"title": "Gravity paper"}, {"title": "riko 4.0"}]
            >>> subscriber = SyncPipe.subscribe("inbox")
            >>>
            >>> _ = list(SyncPipe.publish(items, "inbox"))
            >>> [item["title"] for item in subscriber]
            ['Gravity paper', 'riko 4.0']
            >>> # An idle channel drains to nothing rather than waiting on the publisher
            >>> list(SyncPipe.subscribe("quiet"))
            []

        """
        from riko.modules.receive import register_receiver  # noqa: PLC0415

        conf = ReceiveConf({"name": name, "max_wait": 0})
        extra: dict[str, int | float | None] = {"wait": wait, "max_len": maxlen}

        for key, value in extra.items():
            if value is not None:
                conf[key] = value

        receiver = cls(
            "receive",
            conf=conf,
            func=func,
            assign=assign,
            context=context,
            inputs=inputs,
            skip_if=skip_if,
            test=test,
            verbose=verbose,
        )
        register_receiver(name, maxlen=maxlen, func=func, **kwargs)
        return receiver

    def _release_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.close()

    def _terminate_pool(self) -> None:
        if self._pool_handle:
            self._pool_handle.terminate()

    def close(self) -> None:
        """
        Releases the pipe by letting in-flight worker tasks finish.

        A borrowed pool is left alone and the one this pipe owns is shut down. A
        bound publisher still signals completion to its subscribers, since a graceful
        close means "no more items left to publish".
        """
        self._iter = _settle_iter(self._iter)
        self._release_pool()
        self._close()

    def terminate(self) -> None:
        """
        Releases the pipe by abandoning in-flight worker tasks.

        The abrupt counterpart to :meth:`close`, used on an exceptional context
        exit.
        """
        self._iter = _settle_iter(self._iter)
        self._terminate_pool()
        self._close()

    def __enter__(self) -> Self:
        """
        Enters the pipe context and manages any owned worker pool.

        Examples:
            >>> src = [{"content": "a"}, {"content": "b"}]
            >>>
            >>> with (flow := SyncPipe("hash", source=src, parallel=True)):
            ...     results = list(flow)
            ...     flow.pool  # the worker pool is live inside the block
            <multiprocessing.pool.ThreadPool state=RUN pool_size=2>
            >>> flow.pool  # ... and shut down once the block exits
            >>> len(results)
            2
            >>> # the pool is *terminated* if the block raises
            >>> try:
            ...     with (flow := SyncPipe("hash", source=src, parallel=True)):
            ...         raise RuntimeError("boom")
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
            # A graceful close is "no more items left to publish", so a bound
            # publisher still signals DONE to its subscribers; a real failure below
            # must not, else a failed publisher looks successfully complete.
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
        """
        Eagerly returns independent copies of the stream.

        The source is materialized so each copy can be consumed at its own pace. Use
        ``publish`` for lazy fan-out over an unbounded source.

        Examples:
            >>> items = [{"x": 1}, {"x": 2}]
            >>> first, second = SyncPipe(source=items).split()
            >>> next(first), next(second)
            ({'x': 1}, {'x': 1})

        """
        splits = self._chain("split", **kwargs)
        return cast(SplitterParserOutput, splits)

    @overload
    def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    def export(  # noqa: E704
        self, type_: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | str | Items | None:
        try:
            result = export(self, *args, **kwargs)
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing SyncPipe attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result.getvalue() if isinstance(result, StringIO) else result


class PyCollection(_Lifecycle):
    """
    A bulk fetch over many sources, merged into one stream.

    The engine-agnostic half of a collection. Each source is a ``conf`` mapping
    carrying at least a ``url``, plus an optional ``type`` naming the fetch
    module to use. ``SyncCollection`` and ``AsyncCollection`` add the execution
    model.

    Args:
        sources: One conf mapping per source.
        conf: Defaults merged under every source's own conf.
        workers: Pool size when ``parallel``. Derived from the source count when unset.
        parallel: Whether to fetch sources concurrently.

    """

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
    A synchronous PyCollection object.

    Examples:
        >>> from riko import get_path
        >>>
        >>> sources = [{"url": get_path(f)} for f in ["feed.xml", "gawker.xml"]]
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
        """The live worker pool, or ``None`` when inline or already released."""
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
        """
        Releases the collection by letting in-flight fetches finish.

        A borrowed pool is left alone and the one this collection owns is shut down.
        """
        self._iter = _settle_iter(self._iter)
        self._release_pool()
        self._close()

    def terminate(self) -> None:
        """
        Releases the collection by abandoning in-flight fetches.

        The abrupt counterpart to :meth:`close`, used on an exceptional context exit.
        """
        self._iter = _settle_iter(self._iter)
        self._terminate_pool()
        self._close()

    def __enter__(self) -> Self:
        """
        Enters the collection context and manages any owned worker pool.

        Examples:
            >>> from riko import get_path
            >>>
            >>> sources = [{"url": get_path(f)} for f in ["feed.xml", "gawker.xml"]]
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
            ...         raise RuntimeError("boom")
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
        """Fetches every source url."""
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
        Chains the next pipe by name.

        Examples:
            >>> flow = SyncPipe("itembuilder")
            >>> chained = flow.pipe("hash")
            >>> chained.name, chained.source is flow
            ('hash', True)

        """
        self._require_usable("chain")
        return SyncPipe(name, source=self, **kwargs)

    @overload
    def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    def export(  # noqa: E704
        self, type_: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | str | Items | None:
        result = export(self, *args, **kwargs)
        return result.getvalue() if isinstance(result, StringIO) else result


class AsyncPipe(PyPipe):
    """
    A lazily evaluated, one-shot asynchronous pipe.

    The ``AsyncPipe`` counterpart of ``SyncPipe``: chain the same way, then
    ``await`` the result or iterate it with ``async for``. Concurrency comes
    from ``connections`` rather than a worker pool.

    Loopable pipes may process ahead of partial consumption, so a pipe's
    function can run for items that are never yielded. Limit side-effecting work
    at the pipe (via ``count``/``truncate``) or fully consume the stream. Fully
    draining yields the same result as ``SyncPipe``.

    Args:
        name: Module to run. A source pipe takes no ``source``.
        source: Upstream stream, feed, or another pipe to chain onto.
        conf: The module's configuration.
        connections: Maximum concurrent item tasks. ``0`` is unlimited.
        ordered: Whether results keep source order.

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
        func: Callable | None = None,
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
            self._async_pipe: AsyncPipeParser = pipe_resolver.resolve(
                self.name, "async_pipe"
            )
            self.pollable: bool = getattr(self._async_pipe, "pollable")  # noqa: B009
            self.loopable: bool = getattr(self._async_pipe, "loopable")  # noqa: B009
            self.mapify: bool = self.loopable
        else:
            self._async_pipe = lambda source, **_: async_return(source)
            self.pollable = self.loopable = self.mapify = False

    def __getattr__(self, name: str) -> "AsyncPipe":
        """
        Chains any module by attribute, so ``.sort()`` runs the sort pipe.

        The async counterpart of :meth:`SyncPipe.__getattr__`; every unknown
        non-underscore attribute is treated as a module name.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        return self._chain(name)

    def __or__(self, other: object) -> "AsyncPipe":
        """
        Chains a module name, config pair, or pipe template using ``|``.

        Examples:
            >>> flow = AsyncPipe("itembuilder")
            >>> piped = flow | "hash"
            >>> piped.name, piped.source is flow
            ('hash', True)
            >>> piped = AsyncPipe("itembuilder") | ("sort", {"combine": "a"})
            >>> piped.name, piped.conf
            ('sort', {'combine': 'a'})
            >>> template = AsyncPipe("sort", conf={"combine": "a"})
            >>> piped = AsyncPipe("itembuilder") | template
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
        Seeds a stream on the left of ``|``.

        Examples:
            >>> items = [{"x": 1}, {"x": 2}]
            >>> piped = items | AsyncPipe("sort")
            >>> piped.name, list(piped.source) == items
            ('sort', True)

        """
        if _is_template(self) and _is_source(other):
            primed = self._prime(other)
        else:
            primed = NotImplemented

        return primed

    def _prime(self, source: Items) -> "AsyncPipe":
        """Returns a copy of this pipe template bound to ``source``."""
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
        """Chains the next pipe by name."""
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
        """
        Drains the pipe and returns a **sync** iterator over the result.

        Awaiting is the eager form; use ``async for`` to consume incrementally.
        """
        return self._await_stream().__await__()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> bool:
        await self.aclose()
        return False

    async def aclose(self) -> None:
        """Closes the pipe by stopping the underlying async generator."""
        if self._aiter is None:
            self._aiter = _spent_aiter()
        else:
            await self._aiter.aclose()

        self._close()

    async def split(self, **kwargs: object) -> SplitterParserOutput:
        """
        Returns independent copies of the stream.

        The async counterpart of :meth:`SyncPipe.split`, and equally eager: the
        source is drained so each copy can be consumed at its own pace.
        """
        splits = await self._chain("split", **kwargs)
        return cast(SplitterParserOutput, splits)

    @overload
    async def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    async def export(  # noqa: E704
        self, type_: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    async def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | str | Items | None:
        items = [item async for item in self]

        try:
            result = export(items, *args, **kwargs)
        except AttributeError as e:
            # Reraise as TypeError to avoid confusion with missing AsyncPipe attributes
            raise TypeError(f"Erred while exporting: {e}") from e

        return result.getvalue() if isinstance(result, StringIO) else result

    def _chain(self, name: ModuleNameLike, **kwargs: object) -> "AsyncPipe":
        """Returns the next async pipe with the current runtime settings."""
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
        """Returns the source as a lazy async iterable, preserving ``None``."""
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
        Drains a Feed into a list for a non-Feed-native module parser.

        This is the legacy-parser boundary: everything before it streams
        lazily, everything after it has been materialized. The bounded parallel
        path in ``_stream`` is the only fully-lazy route.

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
        """Converts the AsyncIterator stream to an Awaitable."""
        return iter([item async for item in self])


class AsyncCollection(PyCollection):
    """
    A bulk fetch over many sources, merged into one asynchronous stream.

    The ``AsyncCollection`` counterpart of ``SyncCollection``: ``await`` the
    result or iterate it with ``async for``. Concurrency comes from
    ``connections``; unordered results are merged as each source lands rather
    than batched.

    Examples:
        >>> from riko import get_path, issync, run
        >>>
        >>> sources = [{"url": get_path(f)} for f in ["feed.xml", "gawker.xml"]]
        >>>
        >>> async def main():
        ...     print(len(list(await AsyncCollection(sources))))
        >>>
        >>> print(32) if issync else run(main)
        32

    """

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
        """Closes the collection by stopping the underlying async generator."""
        if self._aiter is None:
            self._aiter = _spent_aiter()
        else:
            await self._aiter.aclose()

        self._close()

    def async_pipe(
        self, name: ModuleNameLike | None = None, **kwargs: Any
    ) -> "AsyncPipe":
        """Chains the next pipe by name."""
        return AsyncPipe(name, source=self, **kwargs)

    @overload
    async def export(self) -> list[Item]: ...  # noqa: E704
    @overload  # noqa: E301
    async def export(  # noqa: E704
        self, type_: Literal["csv", "json", "geojson"], f: str, **kwargs: object
    ) -> int: ...
    async def export(  # noqa: E301
        self, *args: Any, **kwargs: object
    ) -> int | str | Items | None:
        items = [item async for item in self]
        result = export(items, *args, **kwargs)
        return result.getvalue() if isinstance(result, StringIO) else result

    async def _stream(self) -> AsyncGenerator[Item, None]:
        """Fetches every source url."""
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
        """Converts the AsyncIterator stream to an Awaitable."""
        return iter([item async for item in self])


def get_chunksize(length: int, workers: int) -> int:
    """Returns items per worker task, targeting four batches per worker."""
    return (length // (workers * 4)) or 1


def get_worker_cnt(length: int, threads: bool | None = True) -> int:
    """Returns a pool size, capped at the core count (doubled for threads)."""
    multiplier = 2 if threads else 1
    maximum = cpu_count() * multiplier
    return min(length, maximum) if length else maximum


def listpipe(
    args: tuple[Item, SyncPipeParser], **kwargs: BasicValue
) -> list[ParserOutput]:
    """Runs one item through a pipeline, materialized so it can cross a pool."""
    source, pipeline = args
    result = pipeline(source, **kwargs)
    return list(listize(result))


def _fetch_source[T: SyncPipe | AsyncPipe](
    args: tuple[Mapping[str, str], Conf], pipe: type[T]
) -> T:
    """Builds the fetch pipe for one collection source, merging conf under it."""
    source, _conf = args
    conf = {**_conf, **source}
    pipe_name = str(source.get("type", "fetch"))
    return pipe(pipe_name, conf=cast(Conf, conf))


def fetch_source(
    args: tuple[Mapping[str, str], Conf], pipe: type[SyncPipe] = SyncPipe
) -> Stream:
    """Returns a lazy, unstarted iterator over one collection source."""
    return iter(_fetch_source(args, pipe))


def afetch_source(
    args: tuple[Mapping[str, str], Conf], pipe: type[AsyncPipe] = AsyncPipe
) -> AsyncStream:
    """
    Returns a lazy, unstarted async feed for one collection source.

    Unlike ``afetch_source_eager``, this hands back the source's async iterator
    so ``async_merge`` can stream its records incrementally.

    """
    return aiter(_fetch_source(args, pipe))


async def afetch_source_eager(
    args: tuple[Mapping[str, str], Conf], pipe: type[AsyncPipe] = AsyncPipe
) -> Stream:
    """Drains one collection source, for the ordered path that needs it whole."""
    return await _fetch_source(args, pipe)
