# vim: sw=4:ts=4:expandtab
"""
Private asynchronous execution that runs a prepared workflow.

It owns one async exit stack for a run's acquired resources, runs blocking sync
components on worker threads through the bridge, and gives its mappable nodes one shared
limit on items in flight.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from contextlib import AsyncExitStack
from contextvars import ContextVar
from functools import cached_property, partial
from inspect import isasyncgen
from operator import attrgetter
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from attrs import Factory, define, field

from riko.bado._backend import (
    CancelScope,
    CapacityLimiter,
    Event,
    Semaphore,
    fail_after,
    lowlevel,
)
from riko.bado._util import (
    as_awaitable,
    async_partial,
    maybe_aclosing,
    maybe_async,
    syncify,
)
from riko.bado.itertools import (
    aauto_close,
    amap,
    as_async,
    async_flatten,
    async_map_ordered_stream,
    async_map_stream,
)
from riko.base._config import DEFAULT_OUTPUT
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import call_if_distinct
from riko.coercion._sequences import listize
from riko.types._feed import (
    AsyncEnvelopes,
    AsyncEnvelopeStream,
    AsyncItemCall,
    AsyncTrackedCall,
    ItemCall,
    _ItemEnvelope,
)
from riko.types._io import get_async_closer, resolve_closer
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    OwnedPlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
)
from riko.types._wrappers import RunsItems, require_single_output

from ._adapt import (
    async_drain,
    pull_stream,
    require_async_stream,
    require_stream,
    select_embed,
)
from ._concurrency import build_item_call
from ._execution import (
    Acquisition,
    AsyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._prepared import ExecutionExtras
from ._provenance import (
    NodeProvenance,
    agen_result_envelopes,
    arun_tracked_item,
    run_tracked_item,
)
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.lowlevel import RunVar

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._enums import IdentityMode
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import AnyIterable
    from riko.types._workflow import NodeId, OutputName, PortName
    from riko.types._wrappers import AsyncFunc, AsyncModuleWrapperOutput, Func

    from ._prepared import ExecutionPlan, PreparedNode

_get_value = attrgetter("value")


async def _agen_item_stream[T](
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
        async with maybe_aclosing(call(parent.value)) as results:
            envelopes = agen_result_envelopes(node_id, results, parent, identity)

            async for envelope in envelopes:
                yield envelope


@define(eq=False)
class _WorkerLifecycle[T]:
    """
    Enters a sync lifecycle's context manager for an async execution.

    Both its blocking entry and exit run on a worker thread. The sync execution has
    no twin: it enters a sync lifecycle directly.
    """

    _cm: AbstractContextManager[T]

    async def __aenter__(self) -> T:
        return await maybe_async(self._cm.__enter__, inline=False)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        _exit = async_partial(self._cm.__exit__, _inline=False, _abandon_on_cancel=True)
        return bool(await _exit(exc_type, exc, traceback))


@define(eq=False)
class _Reservation:
    """The node threads one run holds until its output stream closes."""

    budget: _ThreadBudget
    count: int
    held: bool = field(default=True, init=False)

    @cached_property
    def limiter(self) -> Limiter:
        """Caps the run's node threads at the number it reserved."""
        return CapacityLimiter(max(self.count, 1))

    def release(self) -> None:
        """Gives the threads back to the budget. A repeated call does nothing."""
        if self.held:
            self.held = False
            self.budget.restore(self.count)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


@define(eq=False)
class _ThreadBudget:
    """
    Shares one event loop's node threads among the async executions running on it.

    A run takes every thread it may hold at once before it reads anything. No run waits
    for a thread while holding threads another run is waiting for.
    """

    total: int
    available: int = field(
        default=Factory(lambda self: self.total, takes_self=True), init=False
    )
    _restored: Event = field(factory=Event, init=False)

    async def reserve(self, count: int) -> _Reservation:
        """Waits until ``count`` node threads are free, then takes them all at once."""
        while count and self.available < count:
            await self._restored.wait()

        self.available -= count
        return _Reservation(self, count)

    def restore(self, count: int) -> None:
        """Gives back ``count`` node threads and wakes the runs waiting for them."""
        self.available += count
        restored, self._restored = self._restored, Event()
        restored.set()


_budgets: RunVar[_ThreadBudget] | None = (
    None if lowlevel is None else lowlevel.RunVar("node_threads")
)
_on_node_thread: ContextVar[bool] = ContextVar("on_node_thread", default=False)


def _resolve_thread_budget() -> _ThreadBudget:
    """Finds the running event loop's node-thread budget and starts it on first use."""
    if _budgets is None:
        msg = "anyio is required to run async executions"
        raise RuntimeError(msg)
    elif (budget := _budgets.get(None)) is None:
        budget = _ThreadBudget(config.node_threads)
        _budgets.set(budget)

    return budget


# the sync execution has no twin until it owns its values per run
@define(eq=False)
class _Owned[T]:
    """
    Wraps an owned value so it closes once with the first compatible closer.

    The flag is set before the close is awaited so that a failing close is not retried,
    and a close that re-enters does nothing. An async-iterable value is read through the
    wrapper.
    """

    _value: AsyncIterable[T] | object
    _closed: bool = field(default=False, init=False)
    inline: bool = field(default=True, kw_only=True)

    @cached_property
    def _stream(self) -> AsyncIterator[T]:
        """Iterates the value's items; only an async-iterable value has any."""
        if not isinstance(self._value, AsyncIterable):
            msg = "only an async-iterable owned value can be iterated"
            raise TypeError(msg)

        return aiter(self._value)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        return await anext(self._stream)

    async def aclose(self) -> None:
        """Closes the value unless it is already closed."""
        if not self._closed:
            self._closed = True

            if (closer := resolve_closer(self._value, is_async=True)) is not None:
                await maybe_async(closer, inline=self.inline, abandon_on_cancel=True)


# the sync execution registers node streams on its exit stack until it owns them per run
@define(eq=False)
class _RunStream[T]:
    """
    One run's output stream, which owns every node stream the run built.

    It also carries the run's context and the thread limiter which the nodes share.
    Closing it closes the streams last built first, output first. It then returns the
    run's node threads. Only the first close does anything.
    """

    _reservation: _Reservation
    context: Context | None
    _steps: list[object] = field(factory=list, init=False)
    _closed: bool = field(default=False, init=False)

    @property
    def limiter(self) -> Limiter:
        """Caps the run's node threads at the number it reserved."""
        return self._reservation.limiter

    @property
    def _output(self) -> AsyncIterator[T]:
        """The endpoint's stream, the step the run built last."""
        if not isinstance(step := self._steps[-1], AsyncIterator):
            msg = "the run's output must be an async iterator"
            raise TypeError(msg)

        return step

    def add(self, *values: object) -> None:
        """Adds the streams the run built, or the values they were drawn from."""
        self._steps.extend(values)

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
                        if (closer := resolve_closer(step, is_async=True)) is not None:
                            stack.push_async_callback(
                                maybe_async,
                                closer,
                                inline=False,
                                abandon_on_cancel=True,
                            )
            finally:
                self._reservation.release()


_timeout = Factory(lambda self: self.settings.shutdown_timeout, takes_self=True)


@define(eq=False)
class AsyncExecution[T](_BaseExecution[AsyncExitStack]):
    """
    Runs a prepared workflow asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge. The execution
    settings decide whether mappable nodes run several items at once. Those nodes all
    share one limit on items in flight.
    """

    shutdown_timeout: float = field(default=_timeout, kw_only=True)
    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _inflight: dict[Resource[object], Event] = field(factory=dict, init=False)
    _reservations: list[_Reservation] = field(factory=list, init=False)

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
    ) -> tuple[BaseException | None, bool]:
        """
        Unwinds the exit stack under a shutdown timeout window.

        If unwinding outlasts ``shutdown_timeout``, the timeout is reported as a cleanup
        failure and does not replace the error or clean exit that ended the
        ``async with`` block. A sync close still running on a worker when time runs out
        is abandoned.

        Returns:

            The exception a native context manager replaced the primary error with, if
            any, and whether the primary error was suppressed.

        """
        raised: BaseException | None = None
        suppressed = False

        try:
            with CancelScope(shield=True), fail_after(self.shutdown_timeout):
                try:
                    unwound = await self._stack.__aexit__(exc_type, exc, traceback)
                    suppressed = bool(unwound)
                except Exception as error:  # noqa: BLE001 (re-raised by _report_shutdown)
                    raised = error
        except TimeoutError as error:
            self._cleanup_errors.append(error)

        return raised, suppressed

    async def _shutdown(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        suppressed = False

        if not self._closing:
            self._closing = True
            raised, suppressed = await self._aunwind(exc_type, exc, traceback)
            self._report_shutdown(exc, raised, suppressed)

        return suppressed

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
        self, func: AsyncFunc[object], *args: object
    ) -> None:
        """Awaits a cleanup callback and saves its failure for the shutdown report."""
        try:
            await func(*args)
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

    def queue_async_callback(self, func: AsyncFunc[object], *args: object) -> None:
        """
        Registers an async ``func`` to run during exit-stack unwind.

        Args:

            func: An async cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add an async callback to")
        self._stack.push_async_callback(self._arecord_cleanup_error, func, *args)

    async def _reserve_threads(self, demand: int, output: OutputName) -> _Reservation:
        """
        Reserves every node thread a run may hold at once before it reads anything.

        Args:

            demand: The max number of node threads the run may hold at once.
            output: The name of the workflow output being run.

        Returns:

            The run's reservation. It is released when its output stream closes or the
            execution shuts down.

        Raises:

            InvalidPipelineError: If ``demand`` exceeds the event loop's node-thread
                budget, or what this execution's open output streams leave free, or if
                the run is read from a node thread and too few threads are free.

        """
        budget = _resolve_thread_budget()
        self._reservations[:] = [r for r in self._reservations if r.held]
        held = sum(r.count for r in self._reservations)

        if demand > budget.total:
            msg = (
                f"workflow output {output!r} may hold {demand} threads at once for "
                "modules without an async implementation. The node-thread budget is "
                f"{budget.total}. Raise RIKO_NODE_THREADS, or shorten the chain of "
                "such modules."
            )
            raise InvalidPipelineError(msg)
        elif held + demand > budget.total:
            msg = (
                f"workflow output {output!r} may hold {demand} threads at once for "
                "modules without an async implementation. This execution's open output "
                f"streams already hold {held} of the node-thread budget of "
                f"{budget.total}. Close them first, or raise RIKO_NODE_THREADS."
            )
            raise InvalidPipelineError(msg)
        elif _on_node_thread.get() and budget.available < demand:
            msg = (
                f"workflow output {output!r} runs inside a module without an async "
                "implementation, for example as a nested stored workflow. It may hold "
                f"{demand} threads at once, but only {budget.available} of the "
                f"node-thread budget of {budget.total} are free. It cannot wait for "
                "threads its parent holds, so raise RIKO_NODE_THREADS."
            )
            raise InvalidPipelineError(msg)

        reservation = await budget.reserve(demand)

        if demand:
            try:
                self.enter_context(reservation)
            except BaseException:
                reservation.release()
                raise

            self._reservations.append(reservation)

        return reservation

    async def _run_node_call[R](
        self, limiter: Limiter | None, func: Func[R], *args: object
    ) -> R:
        """Runs a sync-only node's blocking step on one of the run's node threads."""
        self._require_open("run work in")
        token = _on_node_thread.set(True)

        try:
            result = await maybe_async(func, *args, inline=False, limiter=limiter)
        finally:
            _on_node_thread.reset(token)

        return result

    def register_owned[R](
        self,
        value: R,
        cleanup: Cleanup[R] | Literal[False] | None = None,
        *,
        inline: bool = True,
    ) -> None:
        """
        Registers an owned value to close when the execution exits.

        Args:

            value: The value to close.

        Kwargs:

            cleanup: The cleanup to call with ``value`` in place of its own close, or
                ``False`` to leave it open.

            inline: Whether a sync close or cleanup runs on the event loop rather than
                on a worker thread.

        """
        if (closer := resolve_closer(value, cleanup, is_async=True)) is not None:
            callback = async_partial(closer, _inline=inline, _abandon_on_cancel=True)
            self.queue_async_callback(callback)

    async def _acall_factory[R](self, plan: ValueFactoryPlan[R]) -> R:
        if plan.is_async:
            raw = call_factory(plan)
        else:
            raw = await maybe_async(partial(call_factory, plan), inline=False)

        value = await as_awaitable(raw)
        self.register_owned(value, plan.cleanup, inline=False)
        return value

    async def _aenter_lifecycle[R](self, plan: AsyncLifecyclePlan[R]) -> R:
        return await self.enter_async_context(build_context_manager(plan))

    async def _aenter_sync_lifecycle[R](self, plan: SyncLifecyclePlan[R]) -> R:
        cm = _WorkerLifecycle(build_context_manager(plan))
        return await self.enter_async_context(cm)

    async def _aopen[R](self, plan: ResourcePlan[R]) -> R:
        match plan:
            case ExternalPlan():
                value = plan.value
            case OwnedPlan():
                value = plan.value
                self.register_owned(value, plan.cleanup, inline=False)
            case ValueFactoryPlan():
                value = await self._acall_factory(plan)
            case SyncLifecyclePlan():
                value = await self._aenter_sync_lifecycle(plan)
            case AsyncLifecyclePlan():
                value = await self._aenter_lifecycle(plan)

        return value

    async def aclose(self) -> None:
        """
        Unwinds the exit stack behind a cancellation shield.

        Only the first call shuts the execution down. A repeated call does nothing.
        """
        await self._shutdown()

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
        elif (event := self._inflight.get(resource)) is not None:
            await event.wait()
            entry = await self._acquire_entry_once(resource)
        else:
            event = Event()
            self._inflight[resource] = event

            try:
                entry = await self._aacquire_entry(resource)
                self._acquired[resource] = entry
            finally:
                del self._inflight[resource]
                event.set()

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
    ) -> AsyncIterator[T]:
        """
        Opens a seed as the async stream this execution reads.

        Args:

            seed: Items for the workflow output's open input. An awaitable is resolved
                when the run starts. A seed that is both sync- and async-iterable is
                read asynchronously. The execution closes the seed when it exits.

        """
        resolved = await as_awaitable(seed)

        if isinstance(resolved, AsyncIterable):
            iterator = aiter(resolved)
            owned = (
                _Owned(iterator) if get_async_closer(iterator) is not None else iterator
            )
            stream: AsyncIterator[T] = owned
        else:
            # an unbound T | Iterable[T] defeats listize's overloads
            iterator = owned = iter(cast("Iterable[T]", listize(resolved)))
            stream = as_async(iterator)

        call_if_distinct(self.register_owned, resolved, iterator)
        self.register_owned(owned)
        return stream

    async def _abind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        pairs = self._require_bindings(binding).items()
        values = {slot: await self.aacquire(resource) for slot, resource in pairs}
        return ResourceView(values)

    def _build_async_item_call(
        self, context: Context | None, node: PreparedNode, **extra: object
    ) -> AsyncItemCall[T]:
        """
        Builds a call that lazily runs one mapped node's item.

        Runs synchronous pipes on a worker thread, one result per trip, or on the event-
        loop thread when inline executor is set. Each call runs under the run's
        ``context``.
        """
        interface = node.async_interface

        if interface.native:
            prepared = interface.item_call

            if isinstance(prepared, RunsItems):
                run: Func[object] = partial(prepared.arun_item, context, extra)
            else:
                run = partial(prepared, context=context, **extra)

            async def call_native(item: T) -> AsyncIterator[T]:
                raw = run(item)
                results = cast("AnyIterable[T]", await as_awaitable(raw))

                async with maybe_aclosing(as_async(results)) as stream:
                    async for result in stream:
                        yield result

            call = call_native
        else:
            args = (context, node)
            sync_call: ItemCall[T] = build_item_call(*args, **extra)

            if self.settings.async_policy.inline:

                def call_inline(item: T) -> AsyncIterator[T]:
                    return as_async(sync_call(item))

                call = call_inline
            else:
                worker = partial(self._run_node_call, None)

                def call_pulled(item: T) -> AsyncIterator[T]:
                    results = sync_call(item)
                    pulled = pull_stream(worker, results)
                    return aauto_close(pulled, results, inline=False)

                call = call_pulled

        return call

    def _build_async_tracked_call(
        self, context: Context | None, node: PreparedNode, **extra: object
    ) -> AsyncTrackedCall[T]:
        """
        Builds a call that eagerly runs one mapped node's envelope.

        Runs synchronous pipes on a worker thread in one trip, unless inline executor is
        set.
        """
        interface = node.async_interface
        identity = interface.identity

        if interface.native or self.settings.async_policy.inline:
            call = self._build_async_item_call(context, node, **extra)
            tracked = partial(arun_tracked_item, call, node.node.id, identity)
        else:
            args = (context, node)
            sync_call: ItemCall[T] = build_item_call(*args, **extra)
            run = self.run_sync
            tracked = partial(run, run_tracked_item, sync_call, node.node.id, identity)

        return tracked

    def _amap_stream(
        self, limit: int, call: AsyncTrackedCall[T], envelopes: AsyncEnvelopes[T]
    ) -> AsyncEnvelopeStream[T]:
        """
        Maps a prepared call over a node's envelopes under the execution's item limit.

        Closing the stream early stops its in-flight calls in the consuming task.
        """
        mapper = async_map_ordered_stream if self.settings.ordered else async_map_stream
        args = (call, envelopes)
        mapped = mapper(*args, limit=limit, buffer=0, budget=self._concurrency_budget)
        return async_flatten(mapped)

    async def _run_sync_node(
        self,
        run: _RunStream[_ItemEnvelope[T]],
        node: PreparedNode,
        extras: ExecutionExtras[AsyncEnvelopeStream[T]],
        named: Mapping[PortName, AsyncEnvelopeStream[T]],
        envelopes: AsyncEnvelopes[T],
    ) -> AsyncEnvelopeStream[T]:
        """
        Streams a sync-only node's output stream without materializing it.

        The pipe runs on a worker thread, lazily reads its async input streams, and
        pulls the stream one item at a time as the consumer asks for it. Closing the
        stream closes the pipe and then its async input streams.

        Args:

            run: The run that owns the node's streams, with its context and limiter.
            node: The node, whose synchronous pipe has its call prepared once.
            extras: The keyword arguments the execution adds to the node's call.
            named: The streams wired to the node's named input ports.
            envelopes: The node's primary async input stream.

        Returns:

            The async envelope stream produced by the node.

        """
        interface = node.sync_interface
        args = (node.node.id, interface.identity)
        provenance: NodeProvenance[T] = NodeProvenance.from_identity(*args)
        agen_values = provenance.agen_values
        streams: list[AsyncEnvelopeStream[T]] = []

        def drain(
            _envelopes: AsyncEnvelopes[T], item_normalizer: Func[object] | None = None
        ) -> Iterator[object]:
            node_stream = aiter(_envelopes)
            streams.append(node_stream)
            return async_drain(syncify, agen_values(node_stream, item_normalizer))

        extra = extras.map_kwargs(drain, named)
        _stream = drain(envelopes, interface.item_normalizer)

        def start() -> tuple[object, Iterator[T]]:
            raw = interface.call(_stream, run.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            return raw, require_stream(value, interface.pipe)

        worker = partial(self._run_node_call, run.limiter)
        raw, stream = await worker(start)
        values = (stream,) if raw is stream else (raw, stream)
        owned = [_Owned(value, inline=False) for value in values]
        run.add(*owned)
        pulled = pull_stream(worker, stream)
        tracked = provenance.agen_envelopes(pulled)
        return aauto_close(tracked, *reversed(owned), *streams)

    # differs from the sync twin until the sync execution owns its streams per run
    async def _abuild_whole_stream(
        self,
        run: _RunStream[_ItemEnvelope[T]],
        node: PreparedNode,
        extras: ExecutionExtras[AsyncEnvelopeStream[T]],
        streams: tuple[AsyncEnvelopeStream[T], dict[PortName, AsyncEnvelopeStream[T]]],
    ) -> AsyncEnvelopeStream[T]:
        """
        Builds the output stream of a node that reads its whole input in one call.

        The pipe reads bare values. Each value it passes through keeps its envelope.
        """
        interface = node.async_interface
        _stream, named = streams

        if interface.native:
            args = (node.node.id, interface.identity)
            provenance: NodeProvenance[T] = NodeProvenance.from_identity(*args)
            agen_values = provenance.agen_values
            extra = extras.map_kwargs(agen_values, named)
            values = agen_values(_stream, interface.item_normalizer)
            raw = interface.call(values, run.context, **extra)
            value = cast("AsyncModuleWrapperOutput[T]", raw)
            inner: AsyncIterator[T] = require_async_stream(value, interface.pipe)
            call_if_distinct(run.add, value, inner)

            if (
                not isasyncgen(inner)
                and resolve_closer(inner, is_async=True) is not None
            ):
                inner = _Owned(inner, inline=False)

            run.add(inner)
            stream = provenance.agen_envelopes(inner)
        else:
            args = (run, node, extras, named, _stream)
            stream = await self._run_sync_node(*args)

        return stream

    def _abuild_item_stream(
        self,
        context: Context | None,
        node: PreparedNode,
        extra: dict[str, object],
        stream: AsyncEnvelopeStream[T],
    ) -> AsyncEnvelopeStream[T]:
        """
        Builds a mappable node's envelope stream by running its call once per item.

        When the settings allow concurrency, runs several item calls at once while
        adhering to the execution's item limit.
        """
        require_single_output(node.async_interface.pipe)

        if (limit := self.settings.async_policy.limit) is None:
            call = self._build_async_item_call(context, node, **extra)
            identity = node.async_interface.identity
            envelopes = _agen_item_stream(call, node.node.id, identity, stream)
        else:
            tracked = self._build_async_tracked_call(context, node, **extra)
            envelopes = self._amap_stream(limit, tracked, stream)

        return envelopes

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        steps: AsyncExecSteps[_ItemEnvelope[T]],
        run: _RunStream[_ItemEnvelope[T]],
        node_id: NodeId,
        *,
        seed: AsyncIterator[T] | None,
    ) -> AsyncEnvelopeStream[T]:
        """
        Builds one node's lazy async output stream from its pre-built input streams.

        A mappable node (loopable, with no secondary input stream) runs once per item.
        When the settings allow concurrency, several of its items run at once, and all
        such nodes share one ``async_policy.limit`` on items in flight. Any other node
        reads its whole input in one call. The seed enters as new items of the node it
        feeds.

        Args:

            plan: The prepared workflow being run.
            steps: The streams already built for upstream nodes.
            run: The run that owns the node's streams, with its context and limiter.
            node_id: Id of the node to build.

        Kwargs:

            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy async output stream of envelopes.

        """
        node = plan.nodes[node_id]

        if seed is None:
            roots = None
        else:
            roots = agen_result_envelopes(node_id, seed)

        args = (steps, node.incoming, roots)
        _stream, named, others = self._resolve_node_inputs(*args, as_stream=as_async)
        bind = self._abind_resources
        resources = await bind(node.resources) if node.resources else None

        if node.embed is None:
            embed = None
        else:
            embed = select_embed(
                node.embed,
                host_isasync=node.async_interface.native,
                run_sync=self.run_sync,
                drain=partial(async_drain, syncify),
            )

        extras = ExecutionExtras(others=others, resources=resources, embed=embed)

        if node.is_mappable:
            extra = {**named, **extras.kwargs}
            stream = self._abuild_item_stream(run.context, node, extra, _stream)
        else:
            streams = (_stream, named)
            stream = await self._abuild_whole_stream(run, node, extras, streams)

        return stream

    async def _arun_plan(
        self,
        plan: ExecutionPlan,
        output: OutputName,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
        context: Context | None,
    ) -> AsyncEnvelopeStream[T]:
        """Builds the async envelope stream for a plan's workflow output."""
        plan.require_output(output)
        steps: AsyncExecSteps[_ItemEnvelope[T]] = {}
        demand = plan.get_thread_demand(output)
        reservation = await self._reserve_threads(demand, output)
        run: _RunStream[_ItemEnvelope[T]] = _RunStream(reservation, context)
        self.queue_async_callback(run.aclose)

        try:
            stream = None if seed is None else await self._aopen_seed(seed)
            args = (plan, steps, run)

            for node_id, node_seed in plan.gen_build_order(output, seed=stream):
                _stream = await self._abuild_stream(*args, node_id, seed=node_seed)
                steps[node_id] = _stream
                run.add(steps[node_id])
        except BaseException:
            await run.aclose()
            raise

        return run

    async def arun_envelopes(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> AsyncEnvelopeStream[T]:
        """
        Builds an async envelope stream for a plan's workflow output.

        Each envelope is an item plus run-local identity. Otherwise it behaves like
        ``arun``.

        Args:

            plan: The prepared workflow to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. An
                awaitable is resolved when the run starts. A seed that is both sync- and
                async-iterable is read asynchronously.

                A seed with ``close`` or ``aclose``, sync or async, is closed once when
                the execution exits. When omitted, every node must either be self-
                starting or receive a seed. A plan with no nodes streams the seed back
                unchanged.

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
        resolved, context = self._resolve_plan(plan)

        if resolved.workflow.is_empty:
            _seed = resolved.require_seed(seed, output)
            values = await self._aopen_seed(_seed)
            stream: AsyncEnvelopeStream[T] = amap(_ItemEnvelope, values)
        else:
            stream = await self._arun_plan(resolved, output, seed, context)

        return stream

    async def arun(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> AsyncIterator[T]:
        """
        Builds the async item stream for a plan's workflow output.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``async with`` block so its cleanup
        stays owned.

        A module without an async implementation runs on a worker thread. One that reads
        its whole input in one call keeps its thread while it reads. Those threads come
        from a budget shared by every run on the event loop (``RIKO_NODE_THREADS``). One
        that runs once per item uses a thread only while it processes an item. Those
        calls don't count against the budget.

        A run takes all the threads it may need before reading anything. It waits while
        other executions hold them.

        Args:

            plan: The prepared workflow to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. An
                awaitable is resolved when the run starts. A seed that is both sync- and
                async-iterable is read asynchronously.

                A seed with ``close`` or ``aclose``, sync or async, is closed once when
                the execution exits. When omitted, every node must either be self-
                starting or receive a seed. A plan with no nodes streams the seed back
                unchanged.

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
        run = await self.arun_envelopes(plan, output, seed=seed)
        values = aauto_close(amap(_get_value, run), run)
        self.queue_async_callback(values.aclose)
        return values


__all__ = ["AsyncExecution"]
