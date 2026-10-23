# vim: sw=4:ts=4:expandtab
"""
Private asynchronous execution that runs a prepared workflow.

It owns one async exit stack for a run's acquired resources, runs blocking sync
components on worker threads through the bridge, and shares one in-flight ceiling
across the run's loopable nodes.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Mapping
from contextlib import AsyncExitStack, aclosing, nullcontext
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any, Self, cast

from attrs import Factory, define, field

from riko.bado._backend import (
    CancelScope,
    CapacityLimiter,
    Event,
    Semaphore,
    asyncify,
    fail_after,
    lowlevel,
    run_from_thread,
)
from riko.bado._util import as_awaitable, maybe_aclosing
from riko.bado.itertools import (
    alist,
    as_async,
    async_map_ordered_stream,
    async_map_stream,
)
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    OwnedPlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
)

from ._adapt import (
    async_drain,
    normalize_items,
    pull_stream,
    require_async_stream,
    require_stream,
    select_embed,
)
from ._concurrency import run_item
from ._execution import (
    Acquisition,
    AsyncExecSteps,
    ExtraInput,
    ExtraOutput,
    _Acquired,
    _asyncify_call,
    _BaseExecution,
    _FailedAcquisition,
    _require_source,
)
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_teardown import aclose_resource, close_resource
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.lowlevel import RunVar

    from riko.definitions._resource_definition import Resource
    from riko.types._resource import ResolvedValue, ResourcePlan
    from riko.types._streams import AnyIterable
    from riko.types._wrappers import AsyncFunc, AsyncModuleWrapperOutput

    from ._prepared import ExecutionPlan, PreparedInterface


_worker_drain = partial(async_drain, call=run_from_thread)


def _bridge_inputs[T](
    extra: ExtraInput[T], drain: Callable[[AsyncIterable[T]], Iterator[T]]
) -> ExtraOutput[T]:
    """
    Re-exposes a worker-run node's async input streams as lazy synchronous ones.

    Args:

        extra: The secondary input streams wired for the node, mixed with the non-stream
            values a node may also receive.

        drain: Re-exposes one async stream as a lazy synchronous one.

    Returns:

        The same mapping with every async stream replaced by a lazy synchronous
        stream over it, and every other value left as it is.

    """
    bridged: ExtraOutput[T] = {}

    for key, value in extra.items():
        if isinstance(value, AsyncIterable):
            bridged[key] = drain(value)
        elif isinstance(value, list):
            bridged[key] = [
                drain(v) if isinstance(v, AsyncIterable) else v for v in value
            ]
        else:
            bridged[key] = value

    return bridged


@define(eq=False)
class _WorkerContext[T]:
    """Runs a blocking sync context manager's entry and exit on a worker thread."""

    _cm: AbstractContextManager[T]

    async def __aenter__(self) -> T:
        return await _asyncify_call(self._cm.__enter__)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return bool(await _asyncify_call(self._cm.__exit__, exc_type, exc, traceback))


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
class _ReleasingStream[T]:
    """Wraps an output stream so its node threads return when it ends or closes."""

    _stream: AsyncIterator[T]
    _reservation: _Reservation

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        try:
            item = await anext(self._stream)
        except BaseException:
            self._reservation.release()
            raise

        return item

    async def aclose(self) -> None:
        """Closes the output stream and returns the run's node threads."""
        with self._reservation:
            async with maybe_aclosing(self._stream):
                pass


_timeout = Factory(lambda self: self.settings.shutdown_timeout, takes_self=True)


@define(eq=False)
class AsyncExecution[T](_BaseExecution[AsyncExitStack]):
    """
    Runs a prepared workflow asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge. The
    execution settings decide whether loopable nodes run several items at once
    under one in-flight ceiling shared by the whole run.
    """

    shutdown_timeout: float | None = field(default=_timeout, kw_only=True)
    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _inflight: dict[Resource[Any], Event] = field(factory=dict, init=False)
    _reservations: list[_Reservation] = field(factory=list, init=False)

    @cached_property
    def _concurrency_budget(self) -> Semaphore:
        """Caps the items in flight across every mapped node of the execution."""
        if (limit := self.settings.async_policy.limit) is None:
            msg = "only a concurrent execution maps items under a shared ceiling"
            raise InvalidPipelineError(msg)

        return Semaphore(limit)

    async def __aenter__(self) -> Self:
        return self

    async def _unwind(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> tuple[BaseException | None, bool]:
        """
        Unwinds the exit stack under a cancellation shield within the shutdown timeout.

        Returns the exception a native context manager replaced the primary error
        with, if any, and whether the primary error was suppressed. Exhausting the
        shutdown timeout is recorded as a cleanup failure rather than replacing the
        primary outcome.
        """
        raised: BaseException | None = None
        suppressed = False
        missing_timeout = self.shutdown_timeout is None
        bound = nullcontext() if missing_timeout else fail_after(self.shutdown_timeout)

        try:
            with CancelScope(shield=True), bound:
                try:
                    unwound = await self._stack.__aexit__(exc_type, exc, traceback)
                    suppressed = bool(unwound)
                except Exception as error:  # noqa: BLE001
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
            raised, suppressed = await self._unwind(exc_type, exc, traceback)
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

    def push_async_callback(self, func: AsyncFunc[object], *args: object) -> None:
        """
        Registers an async ``func`` to run during exit-stack unwind.

        Args:

            func: An async cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add an async callback to")
        self._stack.push_async_callback(self._arecord_cleanup_error, func, *args)

    async def run_sync[R](self, func: Callable[..., R], *args: object) -> R:
        """
        Runs a blocking sync callable on a worker thread through the bridge.

        Args:

            func: A synchronous callable to run off the event loop.
            args: Positional arguments forwarded to ``func``.

        Returns:

            The value ``func`` returns.

        """
        self._require_open("run work in")
        return await _asyncify_call(func, *args)

    async def _reserve_threads(self, demand: int, output: str) -> _Reservation:
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
                budget, or what this execution's open output streams leave of it, so
                the run could never get all its threads.

        """
        budget = _resolve_thread_budget()
        self._reservations[:] = [r for r in self._reservations if r.held]
        held = sum(r.count for r in self._reservations)

        if demand > budget.total:
            msg = (
                f"workflow output {output!r} may hold {demand} threads at once for "
                "modules without an async implementation, more than the node-thread "
                f"budget of {budget.total}; raise RIKO_NODE_THREADS or shorten the "
                "chain of such modules"
            )
            raise InvalidPipelineError(msg)
        elif held + demand > budget.total:
            msg = (
                f"workflow output {output!r} may hold {demand} threads at once for "
                f"modules without an async implementation, but this execution's open "
                f"output streams hold {held} of the node-thread budget of "
                f"{budget.total}; close them first or raise RIKO_NODE_THREADS"
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
        self, limiter: Limiter, func: Callable[..., R], *args: object
    ) -> R:
        """Runs a sync-only node's blocking step on one of the run's node threads."""
        self._require_open("run work in")
        return await asyncify(func, limiter=limiter)(*args)

    def _register_teardown(
        self, teardown: Callable, value: object, *, is_async: bool
    ) -> None:
        """Registers ``teardown(value)`` on unwind: on the loop, or a worker if sync."""
        if is_async:
            self.push_async_callback(teardown, value)
        else:
            self.push_async_callback(_asyncify_call, teardown, value)

    async def _acall_factory[R](self, plan: ValueFactoryPlan[R]) -> R:
        if plan.is_async:
            raw = call_factory(plan)
        else:
            raw = await _asyncify_call(partial(call_factory, plan))

        value = await as_awaitable(raw)

        if (cleanup := plan.cleanup) is not False:
            self._register_teardown(cleanup, value, is_async=plan.is_teardown_async)

        return value

    async def _aenter_lifecycle[R](
        self, plan: SyncLifecyclePlan[R] | AsyncLifecyclePlan[R]
    ) -> R:
        match plan:
            case AsyncLifecyclePlan():
                cm: AbstractAsyncContextManager[R] = build_context_manager(plan)
            case SyncLifecyclePlan():
                cm = _WorkerContext(build_context_manager(plan))

        return await self.enter_async_context(cm)

    async def _aopen[R](self, plan: ResourcePlan[R]) -> ResolvedValue[R]:
        match plan:
            case ExternalPlan():
                value = plan.value
            case OwnedPlan():
                value = plan.value
                is_async = plan.is_teardown_async
                close = aclose_resource if is_async else close_resource
                teardown = partial(close, plan.cleanup)
                self._register_teardown(teardown, value, is_async=is_async)
            case ValueFactoryPlan():
                value = await self._acall_factory(plan)
            case SyncLifecyclePlan() | AsyncLifecyclePlan():
                value = await self._aenter_lifecycle(plan)

        return value

    async def _aacquire_entry[R](
        self, resource: Resource[R]
    ) -> Acquisition[ResolvedValue[R]]:
        try:
            value = await self._aopen(resource.plan)
        except Exception as error:  # noqa: BLE001
            entry: Acquisition[ResolvedValue[R]] = _FailedAcquisition(error)
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

    async def _abuild_source_stream(
        self, value: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]]
    ) -> AsyncIterable[T]:
        """Resolves a seed of any accepted shape to one lazy async item stream."""
        resolved = await as_awaitable(value)

        if isinstance(resolved, AsyncIterable):
            stream: AsyncIterable[T] = resolved
        else:
            stream = as_async(normalize_items(resolved))

        return stream

    async def _abind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        pairs = self._require_bindings(binding).items()
        values = {slot: await self.aacquire(resource) for slot, resource in pairs}
        return ResourceView(values)

    def _build_item_call(
        self, interface: PreparedInterface, extra: ExtraInput
    ) -> Callable[[T], Awaitable[Iterable[T]]]:
        """
        Builds a call from a mapped node's pipe that collects one item's results.

        A synchronous pipe runs on a worker thread, or on the event-loop thread
        when the settings choose the inline executor.
        """
        prepared = interface.item_call

        if interface.native:

            async def call_native(item: T) -> Iterable[T]:
                raw = prepared(item, context=self.context, **extra)
                value = await as_awaitable(raw)

                if isinstance(value, AsyncIterable):
                    stream = cast("AsyncIterable[T]", value)
                    results: Iterable[T] = await alist(stream)
                else:
                    results = cast("Iterator[T]", value)

                return results

            call = call_native
        else:
            mapped = partial(prepared, context=self.context, **extra)
            sync_call = cast("Callable[[T], Iterable[T]]", mapped)

            if self.settings.async_policy.inline:

                async def call_inline(item: T) -> Iterable[T]:
                    return run_item(sync_call, item)

                call = call_inline
            else:
                call = partial(self.run_sync, run_item, sync_call)

        return call

    async def _amap_stream(
        self,
        call: Callable[[T], Awaitable[Iterable[T]]],
        source: AsyncIterable[T],
        limit: int,
    ) -> AsyncIterator[T]:
        """
        Maps a prepared call over a node's items under the run's shared ceiling.

        Closing the stream early stops its in-flight calls in the consuming task.
        """
        mapper = async_map_ordered_stream if self.settings.ordered else async_map_stream
        args = (call, source)
        mapped = mapper(*args, limit=limit, buffer=0, budget=self._concurrency_budget)

        async with aclosing(mapped) as results:
            async for result in results:
                for item in result:
                    yield item

    async def _run_sync_node(
        self,
        interface: PreparedInterface,
        source: AsyncIterable[T],
        extra: ExtraInput,
        limiter: Limiter,
    ) -> AsyncIterator[T]:
        """
        Streams a sync-only node's output stream without materializing it.

        The pipe runs on a worker thread, reads its async input streams lazily from
        there, and that stream is pulled one item at a time as the consumer asks
        for it. Closing the stream closes the pipe, then its async input streams.

        Args:

            interface: The node's synchronous pipe and its prepared call.
            source: The node's primary async input stream.
            extra: The node's secondary input streams and non-stream arguments.
            limiter: Caps the run's node threads.

        Returns:

            The async item stream produced by the node.

        """
        upstreams: list[AsyncIterator[T]] = []

        def drain(stream: AsyncIterable[T]) -> Iterator[T]:
            upstream = aiter(stream)
            upstreams.append(upstream)
            return _worker_drain(upstream)

        bridged = _bridge_inputs(extra, drain)
        worker_source = drain(source)

        def start() -> tuple[object, Iterator[T]]:
            raw = interface.call(worker_source, context=self.context, **bridged)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            return raw, require_stream(value, interface.pipe)

        run = partial(self._run_node_call, limiter)
        raw, iterator = await run(start)
        return pull_stream(raw, iterator, *upstreams, pull=run, close=_asyncify_call)

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: AsyncExecSteps,
        seed: AnyIterable[T] | None,
        limiter: Limiter,
    ) -> AsyncIterator[T]:
        """
        Builds one node's lazy async output stream from its already-built input streams.

        When the settings allow concurrency, a loopable node runs several items
        at once under the run's shared in-flight ceiling.

        Args:

            plan: The prepared workflow being run.
            node_id: The node to build.
            steps: The streams already built for upstream nodes.
            seed: The items fed to the node's open input, if any.
            limiter: Caps the run's node threads.

        Returns:

            The node's lazy async output stream.

        """
        node = plan.nodes[node_id]
        interface = node.async_interface
        args = (node.incoming, steps, seed)
        source, extra = self._resolve_node_inputs(*args, as_stream=as_async)

        if node.resources:
            extra["resources"] = await self._abind_resources(node.resources)

        if (embed := node.embed) is not None:
            extra["embed"] = select_embed(
                embed,
                host_isasync=interface.native,
                run_sync=self.run_sync,
                drain=_worker_drain,
            )

        if (limit := self.settings.async_policy.limit) is not None and node.is_mappable:
            call = self._build_item_call(interface, extra)
            stream = self._amap_stream(call, source, limit)
        elif not interface.native:
            stream = await self._run_sync_node(interface, source, extra, limiter)
        else:
            _stream = interface.call(source, context=self.context, **extra)
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = require_async_stream(value, interface.pipe)

        return stream

    async def _arun_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> AsyncIterator[T]:
        """Builds the async item stream for one of the plan's workflow outputs."""
        policy = self.settings.async_policy

        endpoint = plan.require_output(output)
        steps: AsyncExecSteps = {}
        demand = plan.get_thread_demand(output, mapped=policy.limit is not None)
        reservation = await self._reserve_threads(demand, output)

        try:
            seed = None if source is None else await self._abuild_source_stream(source)

            for node_id, node_seed in plan.gen_build_order(output, seed=seed):
                args = (plan, node_id, steps, node_seed, reservation.limiter)
                steps[node_id] = await self._abuild_stream(*args)
        except BaseException:
            reservation.release()
            raise

        stream = steps[endpoint.node]
        return stream if demand == 0 else _ReleasingStream(stream, reservation)

    async def arun(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> AsyncIterator[T]:
        """
        Builds the async item stream for one of the plan's workflow outputs.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``async with`` block so its teardown
        stays owned.

        A module without an async implementation runs on a thread it holds while it
        reads its upstream stream. Every run on one event loop draws those threads from
        one shared budget (``RIKO_NODE_THREADS``), and a run takes all the threads it
        may need before reading anything. It waits while other executions hold them,
        and raises when this execution's own open output streams leave too few.

        Args:

            plan: The prepared workflow to run.

            output: The name of the workflow output to produce.

            source: A seed for the workflow output's open input in place of the
                default empty seed. It can be one item, an item stream, an async item
                stream, or an awaitable resolving to one of those. When omitted, only a
                node with no default or positional input port receives that default. A
                plan with no nodes streams it unchanged as its default output.

        Returns:

            The async item stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If the plan exposes no such workflow output, if it
                has no nodes and no ``source`` is given, if ``source`` is supplied but
                the workflow output has no single open input, if the settings name
                the process executor, or if the workflow output may hold more node
                threads at once than the node-thread budget or what this execution's
                open output streams leave free.

        """
        self._require_open("run")

        if plan.workflow.is_empty:
            _source = _require_source(source, output)
            stream = aiter(await self._abuild_source_stream(_source))
        else:
            stream = await self._arun_plan(plan, output, source)

        return stream

    async def aclose(self) -> None:
        """
        Unwinds the exit stack behind a cancellation shield.

        Only the first call shuts the execution down. A repeated call does nothing.
        """
        await self._shutdown()


__all__ = ["AsyncExecution"]
