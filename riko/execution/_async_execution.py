# vim: sw=4:ts=4:expandtab
"""
Private asynchronous execution that runs an execution plan.

It holds an async exit stack that closes a run's acquired resources and runs blocking
sync components on worker threads. It gives its mappable nodes a shared limit on the
number of concurrent items.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable
from contextlib import AsyncExitStack, aclosing
from functools import cached_property, partial
from itertools import repeat
from operator import attrgetter, itemgetter
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NamedTuple, Self, cast

from attrs import define, field

from riko.bado._backend import (
    CancelScope,
    Event,
    Semaphore,
    fail_after,
    lowlevel,
    move_on_after,
)
from riko.bado._util import (
    amap_values,
    as_awaitable,
    asyncify,
    maybe_aclosing,
    maybe_async,
    syncify,
)
from riko.bado.itertools import (
    AsyncTee,
    aauto_close,
    aislice,
    amap,
    as_async,
    async_flat_map,
)
from riko.base._config import DEFAULT_OUTPUT
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import call_if_distinct, compose, compose_inner
from riko.base._guards import AsyncClosable
from riko.base._iterutils import auto_close, partition, raise_failures
from riko.base._require_guards import require_non_null
from riko.coercion._sequences import listize
from riko.types._feed import (
    AsyncEnvelopes,
    AsyncEnvelopeStream,
    AsyncItemCall,
    AsyncOutputPorts,
    AsyncPortMap,
    AsyncTrackedCall,
    ItemCall,
    _ItemEnvelope,
)
from riko.types._io import resolve_closer
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    ResourcePlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
    ValuePlan,
)
from riko.types._streams import require_any_stream, require_async_stream, require_stream
from riko.types._workflow import OUT
from riko.types._wrappers import RunsItems

from ._adapt import to_async, to_sync
from ._concurrency import build_item_call
from ._execution import (
    DEFAULT_ENVELOPES,
    SHUTDOWN_MSG,
    Acquisition,
    AsyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._prepared import NO_PIPE_MSG, ExecutionExtras, PreparedNode, PreparedSplitter
from ._provenance import (
    NodeProvenance,
    agen_result_envelopes,
    arun_tracked_item,
    run_tracked_item,
)
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView
from ._sync_execution import take_streams

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Awaitable, Iterator
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from riko.bado._backend import CapacityLimiter
    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._enums import IdentityMode
    from riko.types._feed import EnvelopeGenerator
    from riko.types._resource import Cleanup
    from riko.types._streams import AnyIterable, AsyncStreamOf, Cascade, StreamOf
    from riko.types._workflow import NodeId, OutputName, PortKey
    from riko.types._wrappers import AsyncFunc

    from ._adapt import WorkerCall
    from ._execution import _Reservation
    from ._prepared import ExecutionPlan

_get_value = attrgetter("value")


def _aunwrap[T](envelopes: AsyncStreamOf[_ItemEnvelope[T]]) -> aauto_close[T]:
    """Unwraps each envelope's value and closes ``envelopes`` once the stream ends."""
    return aauto_close(amap(_get_value, envelopes), envelopes)


async def _agen_envelopes[T](
    call: AsyncItemCall[T],
    node_id: NodeId,
    identity: IdentityMode | None,
    stream: AsyncEnvelopeStream[T],
) -> AsyncEnvelopeStream[T]:
    """
    Runs a mappable node's per-item call on each envelope's value, one item at a time.

    The item being read is closed when the stream is closed early.
    """
    async for parent in stream:
        results = call(parent.value)
        args = (node_id, results, parent, identity)

        async with aclosing(agen_result_envelopes(*args)) as envelopes:
            async for envelope in envelopes:
                yield envelope


async def _awrap[T](
    values: AsyncStreamOf[T], stream: AsyncEnvelopeStream[object]
) -> AsyncEnvelopeStream[T]:
    """
    Matches each splitter stream value with the input envelope it came from.

    Stops at whichever runs out first and drops stream values past the last input item.
    """
    async for value in values:
        try:
            envelope = await anext(stream)
        except StopAsyncIteration:
            break

        yield envelope.with_value(value)


async def _aclose_streams(primary: BaseException | None, *streams: object) -> None:
    """
    Closes every stream and notes a failed close on ``primary`` when there is one.

    Raises:

        Exception: Whatever the one failing close raises, when there is no ``primary``.
        ExceptionGroup: If several closes fail and there is no ``primary``.

    """
    try:
        await aauto_close(as_async(()), *streams, inline=False).aclose()
    except Exception as failure:  # noqa: BLE001 (noted on the primary or re-raised)
        raise_failures("closing the splitter's streams", failure, primary=primary)


async def _atake_streams(
    limit: int, streams: AsyncIterable[AsyncStreamOf[object]]
) -> list[AsyncStreamOf[object]]:
    """
    Takes up to ``limit`` of a splitter's async streams.

    Closes ``streams`` after taking. When taking one fails, closes each stream it took.
    """
    _streams: list[AsyncStreamOf[object]] = []

    async with aclosing(aislice(streams, limit)) as taken:
        try:
            async for stream in taken:
                _streams.append(stream)
        except BaseException as primary:
            await _aclose_streams(primary, *_streams)
            raise

    return _streams


def _async_queue_close[T](
    callback: Callable[[AsyncFunc[object]], object],
    value: T,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    inline: bool = False,
) -> None:
    """Hands ``callback`` the value's close to await later, if it has one."""
    closer = resolve_closer(value, cleanup=cleanup, is_async=True)

    if closer is not None:
        runner = maybe_async.using(inline=inline, abandon_on_cancel=True)
        callback(runner.partial(closer))


@define(eq=False)
class _WorkerLifecycle[T]:
    """
    Enters a sync lifecycle's context manager for an async execution.

    Both its blocking entry and exit run on a worker thread. The sync execution has
    no twin: it enters a sync lifecycle directly.
    """

    _cm: AbstractContextManager[T]

    async def __aenter__(self) -> T:
        return await asyncify(self._cm.__enter__)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        runner = asyncify.using(abandon_on_cancel=True)
        _exit = runner.partial(self._cm.__exit__)
        return bool(await _exit(exc_type, exc, traceback))


def _gen_from[T](stream: StreamOf[T]) -> StreamOf[T]:
    """
    Passes a stream's items on without closing it.

    Unlike ``yield from``, leaves ``stream`` open when this generator closes.
    """
    for item in stream:  # noqa: UP028
        yield item


@define(eq=False)
class _SyncNodeOutput(AsyncIterator[_ItemEnvelope[object]]):
    """A sync-only node's envelope stream asynchronously read via a worker thread."""

    provenance: NodeProvenance[object]
    results: StreamOf[object]
    envelopes: aauto_close[_ItemEnvelope[object]]

    async def __anext__(self) -> _ItemEnvelope[object]:
        return await anext(self.envelopes)

    async def aclose(self) -> None:
        """Closes the asynchronous envelope stream."""
        await self.envelopes.aclose()

    def gen_envelopes(self) -> EnvelopeGenerator[object]:
        """Wraps the node's sync results in envelopes on the worker thread."""
        return self.provenance.gen_envelopes(_gen_from(self.results))


@define(eq=False)
class _RunStream[T]:
    """
    One run's output stream that closes the streams the run registered with it.

    It also carries the run's context and the thread limiter which the nodes share.
    Closing it closes the streams last built first. It then returns the run's node
    threads. Only the first close does anything.
    """

    context: Context | None
    _reservation: _Reservation
    _steps: list[AsyncClosable] = field(factory=list, init=False)
    output: object = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    @property
    def limiter(self) -> CapacityLimiter:
        """Caps the run's node threads at the number it reserved."""
        return self._reservation.limiter

    @property
    def _output(self) -> AsyncStreamOf[T]:
        """The endpoint's stream that the run reads."""
        if not isinstance(output := self.output, AsyncIterator):
            msg = "the run's output must be an async iterator"
            raise TypeError(msg)

        return output

    def add(self, *streams: AsyncClosable) -> None:
        """Adds streams the built run."""
        self._steps.extend(streams)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        try:
            item = await anext(self._output)
        except BaseException:
            self._reservation.release()
            raise

        return item

    async def aclose(self) -> None:
        """Closes every node stream, last built first, then releases the threads."""
        if not self._closed:
            self._closed = True

            try:
                async with AsyncExitStack() as stack:
                    for step in self._steps:
                        stack.push_async_callback(step.aclose)
            finally:
                self._reservation.release()


class _Taken[T](NamedTuple):
    """A stream plus the async stream that pulls and closes it."""

    raw: StreamOf[T]
    stream: aauto_close[T]


def _call_and_take[R, T, **P](
    run: _RunStream[_ItemEnvelope[object]],
    worker: WorkerCall,
    take: Callable[[R], list[StreamOf[T]]],
    func: Callable[P, R],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> list[_Taken[T]]:
    """
    Calls ``func``, takes its streams, and adds async versions of them to ``run``.

    Returns each stream the pipe returned with the async stream that pulls it through
    ``worker`` and closes it.
    """
    values = take(func(*args, **kwargs))
    streams = [to_async(worker, raw) for raw in values]
    run.add(*streams)
    return list(map(_Taken, values, streams))


@define(eq=False)
class AsyncExecution[T](_BaseExecution[AsyncExitStack]):
    """
    Runs an execution plan asynchronously behind one exit stack.

    Blocking sync components run on a worker thread through the bridge. The execution
    settings decide whether mappable nodes run several items at once. Those nodes all
    share one limit on items in flight.
    """

    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _inflight: dict[Resource[object], Event] = field(factory=dict, init=False)
    is_async: ClassVar[bool] = True

    @cached_property
    def _concurrency_budget(self) -> Semaphore:
        """A cap shared by all mappable nodes on the number of items in flight."""
        if (limit := self.settings.async_policy.limit) is None:
            msg = "only a concurrent execution has an item limit to share"
            raise InvalidPipelineError(msg)

        return Semaphore(limit)

    async def __aenter__(self) -> Self:
        return self

    async def _aunwind(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """
        Unwinds the exit stack under a shutdown timeout window.

        Bounds the whole unwind by the settings' ``shutdown_timeout``. Logs and notes a
        timeout as a cleanup failure on the remaining error. Abandons a sync close
        running on a worker after timeout. If a context manager on the stack raises, its
        error replaces ``exc``. Else if one returns true, the stack suppresses ``exc``.

        Returns:

            Whether the ``exc`` was suppressed.

        Raises:

            Exception: The cleanup failure, when there is only one and ``exc`` was
                suppressed, is ``None``, or is a ``GeneratorExit``.

            ExceptionGroup: All cleanup failures, when there are several and ``exc``
                was suppressed, is ``None``, or is a ``GeneratorExit``.

        """
        suppressed = False
        timeout = self.settings.shutdown_timeout

        with CancelScope(shield=True), move_on_after(timeout) as scope:
            try:
                suppressed = bool(await self._stack.__aexit__(exc_type, exc, traceback))
            except Exception as raised:
                raise_failures(SHUTDOWN_MSG, *self._cleanup_errors, primary=raised)
                raise

        if scope.cancelled_caught:
            msg = f"{SHUTDOWN_MSG} took longer than {timeout} seconds"
            self._cleanup_errors.append(TimeoutError(msg))

        primary = None if suppressed else exc
        raise_failures(SHUTDOWN_MSG, *self._cleanup_errors, primary=primary)
        return suppressed

    async def _shutdown(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        suppressed = False

        if not self._closing:
            self._closing = True
            suppressed = await self._aunwind(exc_type, exc, traceback)

        return suppressed

    async def aclose(self) -> None:
        """
        Unwinds the exit stack behind a cancellation shield.

        Only the first call shuts the execution down. A repeated call does nothing.
        """
        await self._shutdown()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return await self._shutdown(exc_type, exc, traceback)

    async def enter_async_context[R](self, cm: AbstractAsyncContextManager[R]) -> R:
        """
        Enters an async ``cm`` on the execution exit stack.

        Args:

            cm: An asynchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add an async resource to")
        return await self._stack.enter_async_context(cm)

    async def _arecord_cleanup_error(
        self, func: AsyncFunc[object], *args: object, **kwargs: object
    ) -> None:
        """Awaits a cleanup callback and saves its failure for the shutdown report."""
        with self._record_cleanup_errors():
            await func(*args, **kwargs)

    def queue_async_callback(
        self, func: AsyncFunc[object], *args: object, **kwargs: object
    ) -> None:
        """
        Registers an async ``func`` to run during exit-stack unwind.

        Args:

            func: An async callable invoked with ``args`` and ``kwargs`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        Kwargs:

            kwargs: Keyword arguments forwarded to ``func``.

        """
        self._require_open("add an async callback to")
        callback = self._arecord_cleanup_error
        self._stack.push_async_callback(callback, func, *args, **kwargs)

    def async_queue_close[R](
        self,
        value: R,
        cleanup: Cleanup[R] | Literal[False] | None = None,
        *,
        inline: bool = True,
    ) -> None:
        """
        Registers a value to close when the execution exits.

        Args:

            value: The value to close.

        Kwargs:

            cleanup: The cleanup to call with ``value`` in place of its own close, or
                ``False`` to leave it open.

            inline: Whether a sync close or cleanup runs on the event loop rather than
                on a worker thread.

        """
        _async_queue_close(self.queue_async_callback, value, cleanup, inline=inline)

    async def _aopen[R](self, plan: ResourcePlan[R]) -> R:
        match plan:
            case ExternalPlan():
                value = plan.value
            case ValuePlan():
                value = plan.value
                self.async_queue_close(value, plan.cleanup, inline=False)
            case ValueFactoryPlan():
                if plan.is_async:
                    raw = call_factory(plan)
                else:
                    raw = await asyncify(call_factory, plan)

                value = await as_awaitable(raw)
                self.async_queue_close(value, plan.cleanup, inline=False)
            case SyncLifecyclePlan():
                cm = _WorkerLifecycle(build_context_manager(plan))
                value = await self.enter_async_context(cm)
            case AsyncLifecyclePlan():
                cm = build_context_manager(plan)
                value = await self.enter_async_context(cm)

        return value

    async def _aacquire_entry[R](self, resource: Resource[R]) -> Acquisition[R]:
        try:
            value = await self._aopen(resource._plan)
        except Exception as error:  # noqa: BLE001
            entry: Acquisition[R] = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    async def _acquire_entry_once(self, resource: Resource[Any]) -> Acquisition[Any]:
        if resource in self._acquired:
            entry = self._acquired[resource]
        elif (event := self._inflight.get(resource)) is None:
            event = Event()
            self._inflight[resource] = event

            try:
                entry = await self._aacquire_entry(resource)
                self._acquired[resource] = entry
            finally:
                del self._inflight[resource]
                event.set()
        else:
            await event.wait()
            entry = await self._acquire_entry_once(resource)

        return entry

    async def aacquire[R](self, resource: Resource[R]) -> R:
        """
        Acquires ``resource`` for this execution, resolving it at most once.

        A subsequent request for the same resource replays the first outcome:
        the resolved value, or the original failure when acquisition failed.

        Args:

            resource: The resource definition to open.

        Returns:

            The resolved resource value.

        """
        self._require_open("acquire a resource in")
        entry = await self._acquire_entry_once(resource)
        return entry.unwrap()

    async def _aopen_seed(
        self, seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]]
    ) -> AsyncStreamOf[T]:
        """
        Opens a seed as the async stream this execution reads.

        Args:

            seed: Items for the workflow output's open input. An awaitable is resolved
                when the run starts. A seed that is both sync- and async-iterable is
                read asynchronously. The seed closes once the run is done reading it or
                when the execution exits, whichever is first.

        """
        _input = await as_awaitable(seed)

        if isinstance(_input, AsyncIterable):
            iterator = aiter(_input)
            stream: AsyncStreamOf[T] = aauto_close(iterator)
        else:
            iterator = iter(cast("Iterable[T]", listize(_input)))
            stream = to_async(maybe_async, iterator, inline=True)

        call_if_distinct(self.async_queue_close, _input, iterator)
        self.async_queue_close(stream)
        return stream

    def _build_async_item_call(
        self, context: Context | None, node: PreparedNode, /, **extra: object
    ) -> AsyncItemCall[object]:
        """
        Builds a call that lazily runs one mapped node's item.

        Runs synchronous pipes on a worker thread, one result per trip, or on the event-
        loop thread when inline executor is set. Each call runs under the run's
        ``context``.
        """
        if (interface := node.async_interface) is None:
            name = node.module.name
            adapted = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
            args = (context, node, adapted)
            sync_call: ItemCall[object] = build_item_call(*args, **extra)

            if self.settings.async_policy.inline:
                call = compose(as_async, sync_call)
            else:
                worker = self._worker()

                def call_pulled(item: object) -> AsyncStreamOf[object]:
                    return to_async(worker, sync_call(item))

                call = call_pulled
        else:
            prepared = interface.item_call

            if isinstance(prepared, RunsItems):
                run_item = partial(prepared.arun_item, context, extra)
            else:
                run_item = partial(prepared, context=context, **extra)

            async def call_native(item: object) -> AsyncStreamOf[object]:
                raw: AnyIterable[object] = await as_awaitable(run_item(item))
                results = require_any_stream(raw, node.module.name)

                async with maybe_aclosing(as_async(results)) as stream:
                    async for result in stream:
                        yield result

            call = call_native

        return call

    def _build_async_tracked_call(
        self, context: Context | None, node: PreparedNode, /, **extra: object
    ) -> AsyncTrackedCall[object]:
        """
        Builds a call that eagerly runs one mapped node's envelope.

        Runs synchronous pipes on a worker thread in one trip, unless inline executor is
        set.
        """
        node_id = node.node.id

        if (interface := node.async_interface) is None:
            name = node.module.name
            adapted = require_non_null(node.sync_interface, NO_PIPE_MSG, name)

            if self.settings.async_policy.inline:
                call = self._build_async_item_call(context, node, **extra)
                tracked = partial(arun_tracked_item, call, node_id, adapted.identity)
            else:
                bargs = (context, node, adapted)
                sync_call: ItemCall[object] = build_item_call(*bargs, **extra)
                run = partial(run_tracked_item, sync_call, node_id, adapted.identity)
                tracked = partial(self.run_sync, run)
        else:
            call = self._build_async_item_call(context, node, **extra)
            tracked = partial(arun_tracked_item, call, node_id, interface.identity)

        return tracked

    def _to_sync[R](self, stream: AsyncStreamOf[R]) -> StreamOf[R]:
        """Pulls an async stream from a worker thread through the running event loop."""
        return to_sync(syncify, stream)

    def _abuild_envelope_stream(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedNode,
        stream: AsyncEnvelopeStream[object],
        named: AsyncPortMap[object],
        extras: ExecutionExtras[AsyncEnvelopeStream[object]],
        /,
    ) -> AsyncEnvelopeStream[object]:
        """
        Builds a mappable node's envelope stream by running its call once per item.

        When the settings allow concurrency, runs several item calls at once while
        adhering to the execution's item limit. Closing the stream early stops any
        in-progress calls. The stream closes its input when it ends.
        """
        node_id = node.node.id
        context = run.context
        extra = {**named, **extras.kwargs}

        if (limit := self.settings.async_policy.limit) is None:
            call = self._build_async_item_call(context, node, **extra)

            if (interface := node.async_interface) is None:
                name = node.module.name
                adapted = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
                identity = adapted.identity
            else:
                identity = interface.identity

            envelopes = _agen_envelopes(call, node_id, identity, stream)
        else:
            self._require_open("map items in")
            tracked_call = self._build_async_tracked_call(context, node, **extra)
            ordered = self.settings.ordered
            budget = self._concurrency_budget
            envelopes = async_flat_map(
                tracked_call, stream, ordered=ordered, limit=limit, budget=budget
            )

        return aauto_close(envelopes, stream)

    async def _acall_and_take[R, S, **P](
        self,
        run: _RunStream[_ItemEnvelope[object]],
        worker: WorkerCall,
        take: Callable[[R], list[StreamOf[S]]],
        func: Callable[P, R],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> list[_Taken[S]]:
        """
        Runs a sync call and takes its streams in one trip to a node thread.

        Opens, takes, and closes a sync-only splitter's cascade inside the trip. The run
        closes each stream's async stream. Cancelling the trip closes the streams with
        the run. A cancellation that arrives during the trip is raised once it ends.

        """
        result = await worker(_call_and_take, run, worker, take, func, *args, **kwargs)
        await lowlevel.checkpoint()
        return result

    async def _run_sync_node(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedNode,
        envelopes: AsyncEnvelopes[object],
        named: AsyncPortMap[object],
        extras: ExecutionExtras[AsyncEnvelopeStream[object]],
        /,
    ) -> AsyncEnvelopeStream[object]:
        """
        Streams a sync-only node's output stream without materializing it.

        The pipe runs on a worker thread, lazily reads its async input streams, and
        pulls the stream one item at a time as the consumer asks for it. Closing the
        stream closes the pipe and then its async input streams. An input that is
        another sync-only node's output is read on the worker thread.

        Args:

            run: The run the node is built in, with its context and limiter.
            node: The sync-only node being run.
            stream: The node's primary async input stream.
            named: The streams wired to the node's named input ports.
            extras: Keyword arguments the execution adds to the node's call.

        Returns:

            The async envelope stream produced by the node.

        """
        name = node.module.name
        interface = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
        provenance = NodeProvenance.from_identity(node.node.id, interface.identity)
        others = () if extras.others is None else extras.others
        source = aiter(envelopes)
        gen_values = compose(self._to_sync, provenance.agen_values)
        named_values = extras.map_inputs(gen_values, named)
        extra = extras.build_kwargs(named_values)
        normalizer = interface.item_normalizer

        if isinstance(source, _SyncNodeOutput):
            values = provenance.gen_values(source.gen_envelopes(), normalizer)
        else:
            values = self._to_sync(provenance.agen_values(source, normalizer))

        worker = self._worker(limiter=run.limiter)

        def take(value: Iterator[object]) -> list[StreamOf[object]]:
            return [require_stream(value, name)]

        [(raw, taken)] = await self._acall_and_take(
            run, worker, take, interface.call, values, run.context, **extra
        )
        envelope_gen = provenance.agen_envelopes(taken)
        inputs = (*named_values.streams, *others, *named.values(), source)
        envelopes = aauto_close(envelope_gen, taken, values, *inputs, inline=False)
        return _SyncNodeOutput(provenance, raw, envelopes)

    async def _abuild_splitter_ports(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedSplitter,
        stream: AsyncEnvelopeStream[object],
        named: AsyncPortMap[object],
        extras: ExecutionExtras[AsyncEnvelopeStream[object]],
        /,
        *,
        demand: Counter[PortKey],
    ) -> AsyncOutputPorts[object]:
        """
        Builds a stream for each splitter port the run reads.

        Each output item keeps its input item's envelope. Closes ports nothing reads.
        Feeds one copy of the input stream to the splitter and one to each input reader.
        Closing the run closes the copies and the input readers.

        Args:

            run: The run the node is built in, with its context and limiter.
            node: The splitter being run.
            stream: The splitter's primary input stream.
            named: The splitter's named input streams, keyed by port name.
            extras: Keyword arguments the execution adds to the splitter's call.

        Kwargs:

            demand: The number of readers per port.

        Returns:

            The async envelope stream for each port the run reads, keyed by port.

        Raises:

            InvalidPipelineError: If the splitter yields a different number of streams
                than it declares.

            TypeError: If a value the splitter yields is not a stream.

        """
        node_id = node.node.id
        active = [port for port in node.output_ports if demand[node_id, port]]
        tee = AsyncTee(stream, max_lag=config.branch_buffer)
        feed = tee.branch()
        parents = {port: tee.branch() for port in active}
        run.add(tee, *parents.values())
        _values = _aunwrap(feed)
        named_values = extras.map_inputs(_aunwrap, named)
        limit = node.splits + 1

        name = node.module.name

        if (interface := node.async_interface) is None:

            def take(streams: Cascade) -> list[StreamOf[object]]:
                cascade = map(require_stream, streams, repeat(name))
                _streams = auto_close(cascade, streams, bridge=syncify)
                return take_streams(limit, _streams)

            _interface = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
            run.add(_values, *named_values.streams)
            extra = extras.build_kwargs(named_values.map(self._to_sync))

            args = (self._to_sync(_values), run.context)
            call = _interface.call
            worker = self._worker(limiter=run.limiter)
            takens = await self._acall_and_take(run, worker, take, call, *args, **extra)
            streams = [taken.stream for taken in takens]
        else:
            run.add(_values, *named_values.streams)
            extra = extras.build_kwargs(named_values)
            cascade = interface.call(_values, run.context, **extra)
            require = compose_inner(aauto_close, require_async_stream, name)
            streams = await _atake_streams(limit, amap(require, cascade))

        try:
            node.validate_streams(*streams)
        except InvalidPipelineError as primary:
            await _aclose_streams(primary, *streams)
            raise

        pairs = zip(node.output_ports, streams, strict=True)
        read, unread = partition(compose(parents.__contains__, itemgetter(0)), pairs)

        ports: AsyncOutputPorts[object] = {
            port: aauto_close(_awrap(_stream, parents[port]), _stream, parents[port])
            for port, _stream in read
        }

        try:
            await _aclose_streams(None, *(_stream for _, _stream in unread))
        except Exception as primary:
            await _aclose_streams(primary, *ports.values())
            raise

        return ports

    def _register_port(
        self,
        steps: AsyncExecSteps[object],
        run: _RunStream[_ItemEnvelope[object]],
        key: PortKey,
        stream: AsyncEnvelopeStream[object],
        readers: int,
    ) -> None:
        """
        Registers a port's stream so that each of its readers gets its own.

        A port with several readers is shared. Each reader gets its own branch, and
        every reader except the first gets a deep copy of each item.

        Args:

            steps: The streams each upstream port has left to hand out.
            run: The run that closes the port's streams if their reader never does.
            key: The port's node id and canonical port.
            stream: The port's envelope stream.
            readers: The number of readers of the port in the run.

        """
        if not isinstance(stream, AsyncClosable):
            raise TypeError(f"port {key!r} must be closable")

        run.add(stream)

        if readers == 1:
            steps[key] = [stream]
        else:
            max_lag = config.branch_buffer
            tee = AsyncTee(stream, isolate=True, max_lag=max_lag)
            branches = [tee.branch() for _ in range(readers)]
            run.add(tee, *branches)
            steps[key] = [*branches]

    async def _abuild_node_ports(
        self,
        plan: ExecutionPlan,
        steps: AsyncExecSteps[object],
        run: _RunStream[_ItemEnvelope[object]],
        node_id: NodeId,
        *,
        demand: Counter[PortKey],
        seed: AsyncStreamOf[object] | None,
    ) -> AsyncOutputPorts[object]:
        """
        Builds a node's output ports, each an async stream, from its input streams.

        A mappable node (loopable, with no secondary input stream) runs once per item.
        When its settings allow concurrency, multiple items run at once. All such nodes
        share one ``async_policy.limit`` on the number of concurrent items. A mappable
        node with only a synchronous implementation runs its items on worker threads,
        unless the executor is inline.

        A splitter builds one stream per output port it is read from. Any other node
        reads its whole input in one call as bare values. Each value it passes through
        keeps its envelope. ``seed`` enters the node as new items.

        Args:

            plan: The execution plan being run.
            steps: The streams each upstream port has left to hand out.
            run: The run the node is built in, with its context and limiter.
            node_id: Id of the node to build.

        Kwargs:

            demand: The number of readers per port.
            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy async output envelope streams, keyed by output port.

        """
        node = plan.nodes[node_id]
        roots = None if seed is None else agen_result_envelopes(node_id, seed)
        closables = self._resolve_node_inputs(steps, node.incoming, roots)
        named, others = closables.named, closables.others

        if node.resources:
            bindings = self._require_bindings(node.resources)
            resources = ResourceView(await amap_values(self.aacquire, bindings))
        else:
            resources = None

        if closables.stream is None:
            _envelopes = as_async(DEFAULT_ENVELOPES if others is None else ())
        else:
            _envelopes = closables.stream

        match node:
            case PreparedSplitter():
                extras = ExecutionExtras(others=others, resources=resources)
                args = (run, node, _envelopes, named, extras)
                ports = await self._abuild_splitter_ports(*args, demand=demand)
            case PreparedNode():
                embed = self._select_embed(node, self._to_sync)
                extras = ExecutionExtras(
                    others=others, resources=resources, embed=embed
                )

                args = (run, node, _envelopes, named, extras)

                if node.is_mappable:
                    envelopes = self._abuild_envelope_stream(*args)
                elif (interface := node.async_interface) is None:
                    envelopes = await self._run_sync_node(*args)
                else:
                    identity = interface.identity
                    provenance = NodeProvenance.from_identity(node_id, identity)
                    named_values = extras.map_inputs(provenance.agen_values, named)
                    extra = extras.build_kwargs(named_values)
                    normalizer = interface.item_normalizer
                    values = provenance.agen_values(_envelopes, normalizer)
                    raw = interface.call(values, run.context, **extra)

                    stream = require_async_stream(raw, node.module.name)
                    results = aauto_close(stream, inline=False)
                    envelope_gen = provenance.agen_envelopes(results)
                    closables = (results, *named_values.streams, values)
                    envelopes = aauto_close(envelope_gen, *closables, inline=False)

                ports = {OUT: envelopes}

        return ports

    async def _close_failed_run(self, run: _RunStream[_ItemEnvelope[object]]) -> None:
        """
        Closes a run whose build failed, even when the failure is a cancellation.

        The close runs behind a cancellation shield within the shutdown timeout. A
        close that fails or times out is recorded as a cleanup error, so the build
        error stays primary.
        """
        recorded = self._record_cleanup_errors()
        timeout = self.settings.shutdown_timeout

        with recorded, CancelScope(shield=True), fail_after(timeout):
            await run.aclose()

    async def abuild_envelope_stream(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> AsyncEnvelopeStream[T]:
        """
        Builds an async envelope stream for a plan's workflow output.

        Each envelope is an item plus run-local identity. Otherwise it behaves like
        ``arun``. Closing the stream closes every node stream the run built, last built
        first. A run returns its node threads when it closes. The execution closes the
        run when it exits, or at once when building a node fails.

        Args:

            plan: The execution plan to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. Omit it
                when the workflow output is self-starting (default: None).

        Returns:

            The async envelope stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If any of these hold:

                - ``plan`` does not expose ``output``.
                - No ``seed`` is given and a node needs one, or the plan has no nodes.
                - A ``seed`` is given but ``output`` does not have exactly one node for
                  it to feed.
                - A workflow input is missing or invalid.
                - The process executor is chosen.
                - The run may hold more node threads than the event loop's budget, or
                  more than this execution's open output streams leave free.
                - The run is read from a node thread, e.g. a nested stored workflow,
                  and too few threads are free.

        """
        self._require_open("run")
        self.settings.validate_async()
        resolved, context = self._resolve_plan(plan)

        if resolved.workflow.is_empty:
            values = await self._aopen_seed(resolved.require_seed(seed, output))
            envelopes: AsyncEnvelopeStream[T] = amap(_ItemEnvelope, values)
        else:
            endpoint = resolved.require_output(output)
            steps: AsyncExecSteps[object] = {}
            demand = resolved.get_port_demand(output)
            threads = resolved.get_thread_demand(output, is_async=True)

            reservation = await self._reserve_threads(threads, output)
            run: _RunStream[_ItemEnvelope[T]] = _RunStream(context, reservation)
            self.queue_async_callback(run.aclose)

            try:
                stream = None if seed is None else await self._aopen_seed(seed)
                args = (resolved, steps, run)

                for node_id, node_seed in resolved.gen_build_order(output, seed=stream):
                    build = self._abuild_node_ports
                    ports = await build(*args, node_id, demand=demand, seed=node_seed)

                    for port, _stream in ports.items():
                        key = (node_id, port)
                        self._register_port(steps, run, key, _stream, demand[key])

                run.output = steps[endpoint.port_key].pop()
            except BaseException:
                await self._close_failed_run(run)
                raise

            envelopes = run

        return envelopes

    async def arun(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> AsyncStreamOf[T]:
        """
        Builds the async item stream for a plan's workflow output.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``async with`` block so the
        execution closes it.

        A module without an async implementation runs on a worker thread. One that reads
        its whole input in one call keeps its thread while it reads. Those threads come
        from a budget shared by every run on the event loop (``RIKO_NODE_THREADS``). One
        that runs once per item uses a thread only while it processes an item. Those
        calls don't count against the budget.

        A run takes all the threads it may need before reading anything. It waits while
        other executions hold them.

        Args:

            plan: The execution plan to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. Omit it
                when the workflow output is self-starting (default: None).

        Returns:

            The async output item stream.

        Raises:

            InvalidPipelineError: If any of these hold:

                - ``plan`` does not expose ``output``.
                - No ``seed`` is given and a node needs one, or the plan has no nodes.
                - A ``seed`` is given but ``output`` does not have exactly one node for
                  it to feed.
                - A workflow input is missing or invalid.
                - The process executor is chosen.
                - The run may hold more node threads than the event loop's budget, or
                  more than this execution's open output streams leave free.
                - The run is read from a node thread, e.g. a nested stored workflow,
                  and too few threads are free.

        """
        envelopes = await self.abuild_envelope_stream(plan, output, seed=seed)
        values = _aunwrap(envelopes)
        self.queue_async_callback(values.aclose)
        return values


__all__ = ["AsyncExecution"]
