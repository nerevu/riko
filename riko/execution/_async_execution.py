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
from contextvars import ContextVar
from functools import cached_property, partial
from inspect import isasyncgen
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
from riko.bado._util import as_awaitable, async_partial, maybe_async, syncify
from riko.bado.itertools import (
    aauto_close,
    alist,
    as_async,
    async_map_ordered_stream,
    async_map_stream,
)
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_values
from riko.types._io import get_async_closer, resolve_closer
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
)
from ._prepared import ExecutionExtras
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.lowlevel import RunVar

    from riko.definitions._resource_definition import Resource
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import AnyIterable
    from riko.types._wrappers import AsyncFunc, AsyncModuleWrapperOutput, Func

    from ._prepared import ExecutionPlan, PreparedInterface


_worker_drain = partial(async_drain, call=syncify)


@define(eq=False)
class _WorkerContext[T]:
    """Runs a blocking sync context manager's entry and exit on a worker thread."""

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


@define(eq=False)
class _RunStream[T]:
    """
    One run's output stream, which owns every node stream the run built.

    Closing it closes the streams last built first, output first, then returns the run's
    node threads. Only the first close does anything.
    """

    _reservation: _Reservation
    _steps: list[object] = field(factory=list, init=False)
    _closed: bool = field(default=False, init=False)

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
        self, limiter: Limiter, func: Func[R], *args: object
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

    async def _aenter_lifecycle[R](
        self, plan: SyncLifecyclePlan[R] | AsyncLifecyclePlan[R]
    ) -> R:
        match plan:
            case AsyncLifecyclePlan():
                cm: AbstractAsyncContextManager[R] = build_context_manager(plan)
            case SyncLifecyclePlan():
                cm = _WorkerContext(build_context_manager(plan))

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
            case SyncLifecyclePlan() | AsyncLifecyclePlan():
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

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. An
                awaitable is resolved when the run starts. A seed that is both sync- and
                async-iterable is read asynchronously. A seed with ``close`` or
                ``aclose``, sync or async, is closed once when the execution exits.

        """
        resolved = await as_awaitable(seed)

        if not isinstance(resolved, AsyncIterable):
            stream, owner = as_async(normalize_items(resolved)), resolved
        elif get_async_closer(resolved) is not None:
            stream = owner = _Owned(resolved)
        else:
            stream, owner = aiter(resolved), resolved

        self.register_owned(owner)
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
        run: _RunStream[T],
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
            run: The run that owns the node's streams.

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

        def start() -> tuple[object, Iterator[T]]:
            raw = interface.call(_stream, context=self.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            return raw, require_stream(value, interface.pipe)

        worker = partial(self._run_node_call, limiter)
        raw, stream = await worker(start)
        values = (stream,) if raw is stream else (raw, stream)
        owned = [_Owned(value, inline=False) for value in values]
        run.add(*owned)
        return aauto_close(pull_stream(stream, func=worker), *reversed(owned), *streams)

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: AsyncExecSteps[T],
        seed: AnyIterable[T] | None,
        limiter: Limiter,
        run: _RunStream[T],
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
            run: The run that owns the node's streams.

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

            if value is not stream:
                run.add(value)

            if (
                not isasyncgen(stream)
                and resolve_closer(stream, is_async=True) is not None
            ):
                stream = _Owned(stream, inline=False)
        else:
            args = (node.sync_interface, _stream, named, extras, limiter, run)
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

        plan.require_output(output)
        steps: AsyncExecSteps[T] = {}
        demand = plan.get_thread_demand(output, mapped=policy.limit is not None)
        reservation = await self._reserve_threads(demand, output)
        run: _RunStream[T] = _RunStream(reservation)
        self.queue_async_callback(run.aclose)

        try:
            stream = None if seed is None else await self._aopen_seed(seed)

            for node_id, node_seed in plan.gen_build_order(output, seed=stream):
                args = (plan, node_id, steps, node_seed, reservation.limiter, run)
                steps[node_id] = await self._abuild_stream(*args)
                run.add(steps[node_id])
        except BaseException:
            await run.aclose()
            raise

        return run

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
        reads its input stream. Every run on one event loop draws those threads from one
        shared budget (``RIKO_NODE_THREADS``). A run takes all the threads it may need
        before reading anything. It waits while other executions hold them, and raises
        when this execution's own open output streams leave too few. It also raises when
        it runs nested inside such a module and too few threads are free.

        Args:

            plan: The prepared workflow to run.

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. An
                awaitable is resolved when the run starts. A seed that is both sync- and
                async-iterable is read asynchronously. A seed with ``close`` or
                ``aclose``, sync or async, is closed once when the execution exits. A
                plan with no nodes, streams the seed unchanged as its default output.

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
