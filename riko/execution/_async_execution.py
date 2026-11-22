# vim: sw=4:ts=4:expandtab
"""
Private asynchronous execution that runs a prepared workflow.

It owns one async exit stack for a run's acquired resources, runs blocking sync
components on worker threads through the bridge, and gives its mappable nodes one shared
limit on items in flight.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack
from contextvars import ContextVar
from functools import cached_property, partial
from inspect import isasyncgen
from itertools import islice
from operator import attrgetter
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast, overload

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
    async_runner,
    asyncify,
    maybe_aclosing,
    maybe_async,
    syncify,
)
from riko.bado.itertools import (
    AsyncTee,
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
from riko.base._funcutils import call_if_distinct, compose
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
from riko.types._io import get_async_closer, resolve_closer
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    OwnedPlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
)
from riko.types._streams import require_any_stream, require_async_stream, require_stream
from riko.types._workflow import OUT
from riko.types._wrappers import RunsItems

from ._adapt import to_async, to_sync
from ._concurrency import build_item_call
from ._execution import (
    DEFAULT_ENVELOPES,
    Acquisition,
    AsyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._prepared import (
    NO_PIPE_MSG,
    AsyncInterface,
    ExecutionExtras,
    PreparedNode,
    PreparedSplitter,
    SyncInterface,
)
from ._provenance import (
    NodeProvenance,
    agen_result_envelopes,
    arun_tracked_item,
    run_tracked_item,
)
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView
from ._sync_execution import _Owned as _SyncOwned

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Awaitable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.lowlevel import RunVar

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._enums import IdentityMode
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import (
        AnyIterable,
        AsyncCascade,
        AsyncCascadeOf,
        AsyncStreamOf,
        Cascade,
        StreamOf,
    )
    from riko.types._workflow import NodeId, OutputName, PortKey, PortName
    from riko.types._wrappers import AsyncFunc

    from ._adapt import WorkerCall
    from ._prepared import ExecutionPlan

_get_value = attrgetter("value")
_aunwrap = partial(amap, _get_value)


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


async def _collect[T](stream: AsyncStreamOf[T], limit: int) -> list[T]:
    """Collects at most ``limit`` items from an async stream, then closes it."""
    items: list[T] = []

    async with maybe_aclosing(stream) as values:
        async for item in values:
            items.append(item)

            if len(items) >= limit:
                break

    return items


async def _awrap[T](
    values: AsyncStreamOf[T], envelopes: AsyncStreamOf[_ItemEnvelope[object]]
) -> AsyncEnvelopeStream[T]:
    """
    Matches each splitter stream value with the input envelope it came from.

    Stops at whichever runs out first and drops stream values past the last input item.
    """
    async for value in values:
        try:
            envelope = await anext(envelopes)
        except StopAsyncIteration:
            break

        yield envelope.with_value(value)


async def _amaybe_close[T](
    value: T, cleanup: Cleanup[T] | Literal[False] | None = None, inline: bool = False
) -> None:
    """Closes a value now if it has a close."""
    closer = resolve_closer(value, cleanup=cleanup, is_async=True)

    if closer is not None:
        runner = maybe_async.using(inline=inline, abandon_on_cancel=True)
        await runner(closer)


def _queue_async_close[T](
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
    def _stream(self) -> AsyncStreamOf[T]:
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
            await _amaybe_close(self._value, inline=self.inline)


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
    def _output(self) -> AsyncStreamOf[T]:
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
                        _queue_async_close(stack.push_async_callback, step)
            finally:
                self._reservation.release()


def _own_and_add[T](
    run: _RunStream[_ItemEnvelope[T]], value: T, inline: bool = False
) -> _Owned[T]:
    owned: _Owned[T] = _Owned(value, inline=inline)
    run.add(owned)
    return owned


def _call_and_take[R, T, **P](
    run: _RunStream[_ItemEnvelope[object]],
    func: Callable[P, R],
    take: Callable[[R], T] | None,
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> tuple[_Owned[object], R, R | T]:
    """
    Calls ``func``, gives an owned result to ``run``, and takes from ``func``'s result.

    Returns a tuple of the owned result, the raw result, and ``take``'s result (or raw
    result if ``take`` is ``None``).
    """
    value = func(*args, **kwargs)
    owned: _Owned[object] = _own_and_add(run, value, False)
    return owned, value, value if take is None else take(value)


@define(eq=False)
class AsyncExecution[T](_BaseExecution[AsyncExitStack]):
    """
    Runs a prepared workflow asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge. The execution
    settings decide whether mappable nodes run several items at once. Those nodes all
    share one limit on items in flight.
    """

    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _inflight: dict[Resource[object], Event] = field(factory=dict, init=False)
    _reservations: list[_Reservation] = field(factory=list, init=False)
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
    ) -> tuple[BaseException | None, bool]:
        """
        Unwinds the exit stack under a shutdown timeout window.

        If unwinding outlasts the settings' ``shutdown_timeout``, the timeout is
        reported as a cleanup failure and does not replace the error or clean exit that
        ended the ``async with`` block. A sync close still running on a worker when time
        runs out is abandoned.

        Returns:

            The exception a native context manager replaced the primary error with, if
            any, and whether the primary error was suppressed.

        """
        raised: BaseException | None = None
        suppressed = False

        try:
            with CancelScope(shield=True), fail_after(self.settings.shutdown_timeout):
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
        try:
            await func(*args, **kwargs)
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

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

    async def _run_on_node_thread[R, **P](
        self,
        runner: async_runner,
        func: Callable[P, R | Awaitable[R]],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Runs a sync-only node's blocking step on one of the run's node threads."""
        self._require_open("run work in")
        token = _on_node_thread.set(True)

        try:
            result = await runner(func, *args, **kwargs)
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
        _queue_async_close(self.queue_async_callback, value, cleanup, inline=inline)

    async def _acall_factory[R](self, plan: ValueFactoryPlan[R]) -> R:
        if plan.is_async:
            raw = call_factory(plan)
        else:
            raw = await asyncify(call_factory, plan)

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
    ) -> AsyncStreamOf[object]:
        """
        Opens a seed as the async stream this execution reads.

        Args:

            seed: Items for the workflow output's open input. An awaitable is resolved
                when the run starts. A seed that is both sync- and async-iterable is
                read asynchronously. The execution closes the seed when it exits.

        """
        _input = await as_awaitable(seed)

        if isinstance(_input, AsyncIterable):
            iterator = aiter(_input)
            closer = get_async_closer(iterator)
            owned = iterator if closer is None else _Owned(iterator)
            stream: AsyncStreamOf[object] = owned
        else:
            value: object = _input
            iterator = owned = iter(listize(value))
            stream = to_async(maybe_async, iterator)

        call_if_distinct(self.register_owned, _input, iterator)
        self.register_owned(owned)
        return stream

    async def _abind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        pairs = self._require_bindings(binding).items()
        values = {slot: await self.aacquire(resource) for slot, resource in pairs}
        return ResourceView(values)

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
                worker = partial(self._run_on_node_thread, asyncify)

                def call_pulled(item: object) -> AsyncStreamOf[object]:
                    results = sync_call(item)
                    pulled = to_async(worker, results)
                    return aauto_close(pulled, results, inline=False)

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

    async def _amap_stream(
        self,
        limit: int,
        call: AsyncTrackedCall[object],
        envelopes: AsyncEnvelopes[object],
    ) -> AsyncEnvelopeStream[object]:
        """
        Maps a prepared call over a node's envelopes once the consumer pulls.

        Runs under the execution's item limit. Closing the stream early stops any
        task's in-progress calls.
        """
        self._require_open("map items in")
        mapper = async_map_ordered_stream if self.settings.ordered else async_map_stream
        args = (call, envelopes)
        mapped = mapper(*args, limit=limit, buffer=0, budget=self._concurrency_budget)

        async with maybe_aclosing(async_flatten(mapped)) as stream:
            async for envelope in stream:
                yield envelope

    def _to_sync[R](self, stream: AsyncStreamOf[R]) -> StreamOf[R]:
        """Pulls an async stream from a worker thread through the running event loop."""
        return to_sync(syncify, stream)

    def _to_sync_owned[R](self, stream: AsyncStreamOf[R]) -> _SyncOwned[R]:
        """
        Builds a sync owned stream that a worker thread reads through the event loop.

        Closing the owned stream closes ``stream`` on the event loop.
        """
        cleanup = lambda _: syncify(_amaybe_close, stream)
        return _SyncOwned(self._to_sync(stream), cleanup=cleanup)

    def _abuild_item_stream(
        self,
        context: Context | None,
        node: PreparedNode,
        stream: AsyncEnvelopeStream[object],
        /,
        **extra: object,
    ) -> AsyncEnvelopeStream[object]:
        """
        Builds a mappable node's envelope stream by running its call once per item.

        When the settings allow concurrency, runs several item calls at once while
        adhering to the execution's item limit.
        """
        node_id = node.node.id

        if (limit := self.settings.async_policy.limit) is None:
            call = self._build_async_item_call(context, node, **extra)

            if (interface := node.async_interface) is None:
                name = node.module.name
                adapted = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
                identity = adapted.identity
            else:
                identity = interface.identity

            envelopes = _agen_item_stream(call, node_id, identity, stream)
        else:
            tracked = self._build_async_tracked_call(context, node, **extra)
            envelopes = self._amap_stream(limit, tracked, stream)

        return envelopes

    @overload
    async def _call_owned[R, **P](
        self,
        run: _RunStream[_ItemEnvelope[object]],
        worker: WorkerCall,
        func: Callable[P, R],
        take: None,
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> tuple[_Owned[object], R, R]: ...
    @overload
    async def _call_owned[R, U, **P](
        self,
        run: _RunStream[_ItemEnvelope[object]],
        worker: WorkerCall,
        func: Callable[P, R],
        take: Callable[[R], U],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> tuple[_Owned[object], R, U]: ...
    async def _call_owned[R, U, **P](
        self,
        run: _RunStream[_ItemEnvelope[object]],
        worker: WorkerCall,
        func: Callable[P, R],
        take: Callable[[R], U] | None,
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> tuple[_Owned[object], R, R | U]:
        """
        Runs a sync call and takes from its result in one trip to a node thread.

        The run owns the result before anything is taken from it. When ``take`` is not
        ``None``, the result includes the output of ``take(func(…))``. Cancelling the
        trip closes the result with the run. A cancellation that arrives during the trip
        is raised once it ends.
        """
        result = await worker(_call_and_take, run, func, take, *args, **kwargs)
        await lowlevel.checkpoint()
        return result

    async def _run_sync_node(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node_id: NodeId,
        name: str,
        interface: SyncInterface[StreamOf[object]],
        extras: ExecutionExtras[AsyncEnvelopeStream[object]],
        named: Mapping[PortName, AsyncEnvelopeStream[object]],
        envelopes: AsyncEnvelopes[object],
    ) -> AsyncEnvelopeStream[object]:
        """
        Streams a sync-only node's output stream without materializing it.

        The pipe runs on a worker thread, lazily reads its async input streams, and
        pulls the stream one item at a time as the consumer asks for it. Closing the
        stream closes the pipe and then its async input streams.

        Args:

            run: The run that owns the node's streams, with its context and limiter.
            node_id: Id of the node being run.
            name: The node's module name.
            interface: The node's synchronous pipe with its prepared call.
            extras: The keyword arguments the execution adds to the node's call.
            named: The streams wired to the node's named input ports.
            envelopes: The node's primary async input stream.

        Returns:

            The async envelope stream produced by the node.

        """
        provenance = NodeProvenance.from_identity(node_id, interface.identity)
        agen_values = provenance.agen_values
        others = () if extras.others is None else extras.others
        source = aiter(envelopes)
        _envelopes = (*others, *named.values(), source)
        drain = compose(self._to_sync, agen_values)

        extra = extras.map_kwargs(drain, named)
        values = self._to_sync(agen_values(source, interface.item_normalizer))
        worker = partial(self._run_on_node_thread, asyncify.using(limiter=run.limiter))
        owned, raw, _ = await self._call_owned(
            run, worker, interface.call, None, values, run.context, **extra
        )

        pulled = to_async(worker, require_stream(raw, name))
        tracked = provenance.agen_envelopes(pulled)
        return aauto_close(tracked, owned, *_envelopes)

    async def _abuild_whole_stream(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedNode,
        extras: ExecutionExtras[AsyncEnvelopeStream[object]],
        named: AsyncPortMap[object],
        stream: AsyncEnvelopeStream[object],
    ) -> AsyncEnvelopeStream[object]:
        """
        Builds the output stream of a node that reads its whole input in one call.

        The pipe reads bare values. Each value it passes through keeps its envelope.
        """
        if (interface := node.async_interface) is None:
            name = node.module.name
            adapted = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
            args = (run, node.node.id, name, adapted, extras, named, stream)
            envelopes = await self._run_sync_node(*args)
        else:
            args = (node.node.id, interface.identity)
            provenance: NodeProvenance[object] = NodeProvenance.from_identity(*args)
            agen_values = provenance.agen_values
            extra = extras.map_kwargs(agen_values, named)
            values = agen_values(stream, interface.item_normalizer)
            raw = interface.call(values, run.context, **extra)
            results = require_async_stream(raw, node.module.name)
            closer = resolve_closer(results, is_async=True)

            if not isasyncgen(results) and closer is not None:
                results = _Owned(results, inline=False)

            run.add(results)
            envelopes = provenance.agen_envelopes(results)

        return envelopes

    async def _agen_owned(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        interface: AsyncInterface[AsyncCascade],
        values: AsyncStreamOf[object],
        /,
        **extra: object,
    ) -> AsyncCascadeOf[object]:
        """Runs a splitter and yields each of its owned streams."""
        cascade = interface.call(values, run.context, **extra)
        run.add(cascade)

        async for stream in cascade:
            yield _own_and_add(run, stream, True)

    async def _aadapt_interface(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        interface: SyncInterface[Cascade],
        values: AsyncStreamOf[object],
        /,
        *,
        limit: int,
        **extra: object,
    ) -> AsyncCascadeOf[object]:
        """
        Runs a sync-only splitter on a worker thread.

        Calls the splitter, opens its cascade, and takes up to ``limit`` streams on the
        thread. Closing a yielded stream closes its sync stream.
        """
        runner = asyncify.using(limiter=run.limiter)
        worker = partial(self._run_on_node_thread, runner)

        *_, streams = await self._call_owned(
            run,
            worker,
            interface.call,
            lambda cascade: list(islice(cascade, limit)),
            self._to_sync(values),
            run.context,
            **extra,
        )

        for stream in streams:
            pulled = aauto_close(to_async(worker, stream), stream, inline=False)
            run.add(pulled)
            yield pulled

    async def _abuild_splitter_ports(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedSplitter,
        extras: ExecutionExtras[AsyncEnvelopeStream[object]],
        named: AsyncPortMap[object],
        stream: AsyncEnvelopeStream[object],
        *,
        demand: Counter[PortKey],
    ) -> AsyncOutputPorts[object]:
        """
        Builds the splitter's output by giving each port the run reads a stream.

        Unwraps the input envelopes and feeds their values to the splitter. Afterwards,
        wraps the splitter output items back into their original envelopes. A stream
        nothing reads is closed before anything is read.

        Args:

            run: The run that owns the node's streams, with its context and limiter.
            node: The splitter being run.
            extras: The keyword arguments the execution adds to the splitter's call.
            named: The splitter's named input streams, keyed by port name.
            stream: The splitter's primary input stream.

        Kwargs:

            demand: The number of readers per port.

        Returns:

            The async envelope stream for each port the run reads, keyed by port.

        Raises:

            InvalidPipelineError: If the splitter yields a different number of streams
                than it declares.

        """
        node_id = node.node.id
        active = [port for port in node.output_ports if demand[node_id, port]]
        tee = AsyncTee(stream, max_lag=config.branch_buffer)
        feed = tee.branch()
        parents = {port: tee.branch() for port in active}
        run.add(tee, feed, *parents.values())
        values = _aunwrap(feed)

        def drain(envelopes: AsyncEnvelopeStream[object]) -> StreamOf[object]:
            node_stream = _aunwrap(envelopes)
            run.add(envelopes, node_stream)
            return self._to_sync(node_stream)

        limit = node.splits + 1

        if (interface := node.async_interface) is None:
            name = node.module.name
            _interface = require_non_null(node.sync_interface, NO_PIPE_MSG, name)
            args = (run, _interface, values)
            extra = extras.map_kwargs(drain, named)
            _owned = self._aadapt_interface(*args, limit=limit, **extra)
        else:
            args = (run, interface, values)
            extra = extras.map_kwargs(_aunwrap, named)
            _owned = self._agen_owned(*args, **extra)

        owned = await _collect(_owned, limit)
        ports: AsyncOutputPorts[object] = {}
        node.validate_streams(*owned)

        for port, owned_stream in zip(node.output_ports, owned, strict=True):
            if (parent := parents.get(port)) is None:
                await _amaybe_close(owned_stream)
            else:
                envelopes = _awrap(owned_stream, parent)
                ports[port] = aauto_close(envelopes, owned_stream, parent)

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
            run: The run that owns the port's streams.
            key: The port's node id and canonical port.
            stream: The port's envelope stream.
            readers: The number of readers of the port in the run.

        """
        run.add(stream)

        if readers == 1:
            steps[key] = [stream]
        else:
            max_lag = config.branch_buffer
            tee = AsyncTee(stream, isolate=True, max_lag=max_lag)
            steps[key] = [tee.branch() for _ in range(readers)]
            run.add(tee, *steps[key])

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
        When the settings allow concurrency, multiple items run at once. All such nodes
        share one ``async_policy.limit`` on the number of concurrent items. A mappable
        node with only a synchronous implementation then runs its items on worker
        threads, unless the executor is inline.

        A splitter builds one stream per output port it is read from. Any other node
        reads its whole input in one call. ``seed`` enters the node as new items.

        Args:

            plan: The prepared workflow being run.
            steps: The streams each upstream port has left to hand out.
            run: The run that owns the node's streams, with its context and limiter.
            node_id: Id of the node to build.

        Kwargs:

            demand: The number of readers per port.
            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy async output envelope streams, keyed by output port.

        """
        node = plan.nodes[node_id]
        roots = None if seed is None else agen_result_envelopes(node_id, seed)
        inputs = self._resolve_node_inputs(steps, node.incoming, roots)
        named, others = inputs.named, inputs.others
        bind = self._abind_resources
        resources = await bind(node.resources) if node.resources else None

        if inputs.stream is None:
            _stream = as_async(DEFAULT_ENVELOPES if others is None else ())
        else:
            _stream = inputs.stream

        match node:
            case PreparedSplitter():
                extras = ExecutionExtras(others=others, resources=resources)
                args = (run, node, extras, named, _stream)
                ports = await self._abuild_splitter_ports(*args, demand=demand)
            case PreparedNode():
                embed = self._select_embed(node, self._to_sync_owned)
                extras = ExecutionExtras(
                    others=others, resources=resources, embed=embed
                )

                if node.is_mappable:
                    args = (run.context, node, _stream)
                    envelopes = self._abuild_item_stream(
                        *args, **named, **extras.kwargs
                    )
                else:
                    args = (run, node, extras, named, _stream)
                    envelopes = await self._abuild_whole_stream(*args)

                ports = {OUT: envelopes}

        return ports

    async def _close_failed_run(self, run: _RunStream[_ItemEnvelope[object]]) -> None:
        """
        Closes a run whose build failed, even when the failure is a cancellation.

        The close runs behind a cancellation shield within the shutdown timeout.
        """
        try:
            with CancelScope(shield=True), fail_after(self.settings.shutdown_timeout):
                await run.aclose()
        except TimeoutError as error:
            self._cleanup_errors.append(error)

    async def _abuild_run(
        self,
        plan: ExecutionPlan,
        output: OutputName,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
        context: Context | None,
    ) -> AsyncEnvelopeStream[object]:
        """
        Builds the async envelope stream for a plan's workflow output.

        The run closes every node stream it built when its output closes, last built
        first, then returns its node threads. The execution closes the run when it
        exits. It also closes the streams at once when building a later node fails.
        """
        endpoint = plan.require_output(output)
        steps: AsyncExecSteps[object] = {}
        demand = plan.get_port_demand(output)
        threads = plan.get_thread_demand(output)
        reservation = await self._reserve_threads(threads, output)
        run: _RunStream[_ItemEnvelope[object]] = _RunStream(reservation, context)
        self.queue_async_callback(run.aclose)

        try:
            stream = None if seed is None else await self._aopen_seed(seed)
            args = (plan, steps, run)
            build = self._abuild_node_ports

            for node_id, node_seed in plan.gen_build_order(output, seed=stream):
                ports = await build(*args, node_id, demand=demand, seed=node_seed)

                for port, _stream in ports.items():
                    key = (node_id, port)
                    self._register_port(steps, run, key, _stream, demand[key])

            endpoint_stream = steps[endpoint.port_key].pop()
            run.add(endpoint_stream)
        except BaseException:
            await self._close_failed_run(run)
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
        self.settings.validate_async()
        resolved, context = self._resolve_plan(plan)

        if resolved.workflow.is_empty:
            _seed = resolved.require_seed(seed, output)
            values = await self._aopen_seed(_seed)
            envelopes: AsyncEnvelopeStream[object] = amap(_ItemEnvelope, values)
        else:
            envelopes = await self._abuild_run(resolved, output, seed, context)

        # node streams carry plain objects; the items match the caller's seed type
        return cast("AsyncEnvelopeStream[T]", envelopes)

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
        envelopes = await self.arun_envelopes(plan, output, seed=seed)
        values = aauto_close(amap(_get_value, envelopes), envelopes)
        self.queue_async_callback(values.aclose)
        return values


__all__ = ["AsyncExecution"]
