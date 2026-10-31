# vim: sw=4:ts=4:expandtab
"""
Private asynchronous execution that runs a prepared workflow.

It owns one async exit stack for a run's acquired resources, runs blocking sync
components on worker threads through the bridge, and shares one in-flight ceiling
across the run's loopable nodes.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable, Mapping
from contextlib import AsyncExitStack, aclosing
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
from riko.bado._util import as_awaitable
from riko.bado.itertools import (
    alist,
    as_async,
    async_map_ordered_stream,
    async_map_stream,
)
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.base._iterutils import map_values
from riko.types._io import AsyncCloseable, is_async_closeable, is_sync_closeable
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
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
    asyncify_call,
)
from ._prepared import ExecutionExtras
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_cleanup import aclose_resource, aclose_with, close_resource
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


def _await_from_thread[T](func: Callable[[], Awaitable[T]]) -> T:
    """Runs ``func`` to completion on the event loop from a worker thread."""

    async def await_func() -> T:
        return await func()

    return run_from_thread(await_func)


_worker_drain = partial(async_drain, call=_await_from_thread)


@define(eq=False)
class _WorkerContext[T]:
    """Runs a blocking sync context manager's entry and exit on a worker thread."""

    _cm: AbstractContextManager[T]

    async def __aenter__(self) -> T:
        return await asyncify_call(self._cm.__enter__)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return bool(await asyncify_call(self._cm.__exit__, exc_type, exc, traceback))


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
class _OwnedSeed[T]:
    """
    Wraps a closeable async seed so the run and the execution close it only once.

    The root node closes its source when the run stops, and the execution closes the
    seed again on exit. Only the first ``aclose`` reaches the seed.
    """

    _stream: AsyncIterator[T] = field(converter=aiter)
    _seed: AsyncCloseable
    _closed: bool = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> T:
        return await anext(self._stream)

    async def aclose(self) -> None:
        """Closes the seed unless it is already closed."""
        if not self._closed:
            self._closed = True
            await self._seed.aclose()


@define(eq=False)
class _NodeStreams:
    """
    Owns the node streams one run builds, so each one closes exactly once.

    A sync node run on a worker closes its inputs as soon as it finishes. The run closes
    whatever is still open when it ends.
    """

    _streams: list[AsyncIterator[object]] = field(factory=list, init=False)
    _closed: set[int] = field(factory=set, init=False)

    def add(self, stream: AsyncIterator[object]) -> None:
        """Adds a node stream the run built."""
        self._streams.append(stream)

    async def _aclose_one(self, stream: AsyncIterator[object]) -> None:
        if (sid := id(stream)) not in self._closed:
            if is_async_closeable(stream):
                await stream.aclose()

            self._closed.add(sid)

    async def aclose(self, *streams: AsyncIterator[object]) -> None:
        """Closes each of ``streams`` that is still open, last one first."""
        async with AsyncExitStack() as stack:
            for stream in streams:
                stack.push_async_callback(self._aclose_one, stream)

    async def aclose_all(self, reservation: _Reservation) -> None:
        """Closes every open node stream, last built first, then releases threads."""
        try:
            await self.aclose(*self._streams)
        finally:
            reservation.release()


@define(eq=False)
class _RunStream[T]:
    """
    Wraps a run's output stream so closing it closes every stream the run built.

    The node streams close in reverse build order, output first, and the run's node
    threads return once they have.
    """

    _stream: AsyncIterator[T]
    _node_streams: _NodeStreams
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
        """Closes the output stream and its node streams, and releases the threads."""
        await self._node_streams.aclose_all(self._reservation)


_timeout = Factory(lambda self: self.settings.shutdown_timeout, takes_self=True)


@define(eq=False)
class AsyncExecution[T](_BaseExecution[AsyncExitStack]):
    """
    Runs a prepared workflow asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge. The
    execution settings decide whether loopable nodes run several items at once
    under one in-flight ceiling shared by the whole run.
    """

    shutdown_timeout: float = field(default=_timeout, kw_only=True)
    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _inflight: dict[Resource[object], Event] = field(factory=dict, init=False)
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

        try:
            with CancelScope(shield=True), fail_after(self.shutdown_timeout):
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

    def queue_async_callback(self, func: AsyncFunc[object], *args: object) -> None:
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
        return await asyncify_call(func, *args)

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
                budget, or what this execution's open output streams leave free.

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

    def _register_cleanup(
        self, cleanup: Callable, value: object, *, is_async: bool
    ) -> None:
        """Registers ``cleanup(value)`` on unwind: on the loop, or a worker if sync."""
        if is_async:
            self.queue_async_callback(cleanup, value)
        else:
            self.queue_async_callback(aclose_with, cleanup, value)

    async def _acall_factory[R](self, plan: ValueFactoryPlan[R]) -> R:
        if plan.is_async:
            raw = call_factory(plan)
        else:
            raw = await asyncify_call(partial(call_factory, plan))

        value = await as_awaitable(raw)

        if (cleanup := plan.cleanup) is not False:
            self._register_cleanup(cleanup, value, is_async=plan.requires_async_cleanup)

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
                is_async = plan.has_async_cleanup
                close = aclose_resource if is_async else close_resource
                cleanup = partial(close, plan.cleanup)
                self._register_cleanup(cleanup, value, is_async=is_async)
            case ValueFactoryPlan():
                value = await self._acall_factory(plan)
            case SyncLifecyclePlan() | AsyncLifecyclePlan():
                value = await self._aenter_lifecycle(plan)

        return value

    async def aclose(self) -> None:
        """
        Unwinds the exit stack behind a cancellation shield.

        Only the first call shuts the execution down. A repeated call does nothing.
        """
        await self._shutdown()

    async def _aacquire_entry[R](
        self, resource: Resource[R]
    ) -> Acquisition[ResolvedValue[R]]:
        try:
            value = await self._aopen(resource._plan)
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

    async def _aopen_seed(
        self, seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]]
    ) -> AsyncIterator[T]:
        """
        Opens a seed as the async stream this execution reads.

        Args:

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. An
                awaitable is resolved when the run starts. A seed that is both sync- and
                async-iterable is read asynchronously. A seed with ``close`` or
                ``aclose`` is closed when the execution exits.

        """
        resolved = await as_awaitable(seed)

        if not isinstance(resolved, AsyncIterable):
            stream, owner = as_async(normalize_items(resolved)), resolved
        elif is_async_closeable(resolved):
            stream = owner = _OwnedSeed(resolved, resolved)
        else:
            stream, owner = aiter(resolved), resolved

        if is_async_closeable(owner):
            self.queue_async_callback(owner.aclose)
        elif is_sync_closeable(owner):
            self.queue_callback(owner.close)

        return stream

    async def _abind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        pairs = self._require_bindings(binding).items()
        values = {slot: await self.aacquire(resource) for slot, resource in pairs}
        return ResourceView(values)

    def _build_item_call(
        self, interface: PreparedInterface, **extra: object
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
        items: AsyncIterable[T],
        limit: int,
    ) -> AsyncIterator[T]:
        """
        Maps a prepared call over a node's items under the run's shared ceiling.

        Closing the stream early stops its in-flight calls in the consuming task.
        """
        mapper = async_map_ordered_stream if self.settings.ordered else async_map_stream
        args = (call, items)
        mapped = mapper(*args, limit=limit, buffer=0, budget=self._concurrency_budget)

        async with aclosing(mapped) as results:
            async for result in results:
                for item in result:
                    yield item

    async def _run_sync_node(
        self,
        interface: PreparedInterface,
        items: AsyncIterable[T],
        named: Mapping[str, AsyncIterator[T]],
        extras: ExecutionExtras[AsyncIterator[T]],
        limiter: Limiter,
        node_streams: _NodeStreams,
    ) -> AsyncIterator[T]:
        """
        Streams a sync-only node's output stream without materializing it.

        The pipe runs on a worker thread, lazily reads its async input streams, and
        pulls the stream one item at a time as the consumer asks for it. Closing the
        stream closes the pipe and then its async input streams.

        Args:

            interface: The node's synchronous pipe, with its call prepared once.
            items: The node's primary async input stream.
            named: The streams wired to the node's named input ports.
            extras: The keyword arguments the execution adds to the node's call.
            limiter: Caps the run's node threads.
            node_streams: The run's node streams.

        Returns:

            The async item stream produced by the node.

        """
        streams: list[AsyncIterator[T]] = []

        def drain(_items: AsyncIterable[T]) -> Iterator[T]:
            node_stream = aiter(_items)
            streams.append(node_stream)
            return _worker_drain(node_stream)

        extra = {**map_values(drain, named), **extras.map_others(drain).kwargs}
        _stream = drain(items)

        def start() -> Iterator[T]:
            raw = interface.call(_stream, context=self.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            return require_stream(value, interface.pipe)

        run = partial(self._run_node_call, limiter)
        stream = await run(start)
        close = partial(node_streams.aclose, *streams)
        return pull_stream(stream, pull=run, close=close)

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: AsyncExecSteps,
        seed: AnyIterable[T] | None,
        limiter: Limiter,
        node_streams: _NodeStreams,
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
            node_streams: The run's node streams.

        Returns:

            The node's lazy async output stream.

        """
        node = plan.nodes[node_id]
        interface = node.async_interface
        native = interface.native
        args = (node.incoming, steps, seed)
        _stream, named, others = self._resolve_node_inputs(*args, as_stream=as_async)
        bind = self._abind_resources
        resources = await bind(node.resources) if node.resources else None

        if node.embed is None:
            embed = None
        else:
            embed = select_embed(
                node.embed,
                host_isasync=interface.native,
                run_sync=self.run_sync,
                drain=_worker_drain,
            )

        extras = ExecutionExtras(others=others, resources=resources, embed=embed)
        extra = {**named, **extras.kwargs}

        if (limit := self.settings.async_policy.limit) is not None and node.is_mappable:
            call = self._build_item_call(interface, **extra)
            stream = self._amap_stream(call, _stream, limit)
        elif native:
            _stream = interface.call(_stream, context=self.context, **extra)
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = require_async_stream(value, interface.pipe)
        else:
            args = (node.sync_interface, _stream, named, extras, limiter, node_streams)
            stream = await self._run_sync_node(*args)

        return stream

    async def _arun_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> AsyncIterator[T]:
        """Builds the async item stream for one of the plan's workflow outputs."""
        policy = self.settings.async_policy

        endpoint = plan.require_output(output)
        steps: AsyncExecSteps = {}
        demand = plan.get_thread_demand(output, mapped=policy.limit is not None)
        reservation = await self._reserve_threads(demand, output)
        node_streams = _NodeStreams()

        try:
            stream = None if seed is None else await self._aopen_seed(seed)

            for node_id, node_seed in plan.gen_build_order(output, seed=stream):
                limiter = reservation.limiter
                args = (plan, node_id, steps, node_seed, limiter, node_streams)
                steps[node_id] = await self._abuild_stream(*args)
                node_streams.add(steps[node_id])
        except BaseException:
            await node_streams.aclose_all(reservation)
            raise

        return _RunStream(steps[endpoint.node], node_streams, reservation)

    async def arun(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> AsyncIterator[T]:
        """
        Builds the async item stream for one of the plan's workflow outputs.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``async with`` block so its cleanup
        stays owned.

        A module without an async implementation runs on a thread it holds while it
        reads its input stream. Every run on one event loop draws those threads from
        one shared budget (``RIKO_NODE_THREADS``), and a run takes all the threads it
        may need before reading anything. It waits while other executions hold them,
        and raises when this execution's own open output streams leave too few.

        Args:

            plan: The prepared workflow to run.

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. An
                awaitable is resolved when the run starts. A seed that is both sync- and
                async-iterable is read asynchronously. A seed with ``close`` or
                ``aclose`` is closed when the execution exits. A plan with no nodes
                streams the seed unchanged as its default output.

                When omitted, every node whose default input port gets no input stream
                must be self-starting (a source module, or a node that only feeds named
                input ports).

        Returns:

            The async item stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If ``output`` is not exposed by ``plan``; if ``seed``
                isn't given and a node requires one, or the plan has no nodes; if
                ``seed`` is given but the ``plan``'s ``output`` doesn't have exactly one
                node for it to feed; if the process executor is chosen; or if the
                workflow output thread's demand exceeds the event loop's node-thread
                budget, or what this execution's open output streams leave free.

        """
        self._require_open("run")

        if plan.workflow.is_empty:
            _seed = plan.require_seed(seed, output)
            stream = aiter(await self._aopen_seed(_seed))
        else:
            stream = await self._arun_plan(plan, output, seed)

        return stream


__all__ = ["AsyncExecution"]
