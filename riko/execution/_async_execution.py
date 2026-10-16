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
from itertools import chain
from typing import TYPE_CHECKING, Any, Literal, Self, cast, overload

from attrs import Factory, define, field

from riko.bado._backend import (
    CancelScope,
    CapacityLimiter,
    Event,
    Semaphore,
    asyncify,
    current_default_thread_limiter,
    fail_after,
    run_from_thread,
)
from riko.bado._util import as_awaitable
from riko.bado.itertools import (
    alist,
    as_async,
    async_map_ordered_stream,
    async_map_stream,
)
from riko.base.exceptions import InvalidPipelineError
from riko.types._guards import is_async_callable

from ._adapt import (
    async_drain,
    normalize_items,
    pull_stream,
    require_async_stream,
    require_stream,
    select_embed,
)
from ._concurrency import AsyncPolicy, is_mappable, resolve_async_policy, run_item
from ._execution import (
    Acquisition,
    AsyncExecSteps,
    ExtraInput,
    ExtraObjects,
    _Acquired,
    _asyncify_call,
    _BaseExecution,
    _FailedAcquisition,
    _is_async_only_closeable,
    _require_source,
)
from ._resource_plan import (
    _ResourcePlan,
    _ResourceStrategy,
    aclose_resource,
    build_resource_plan,
    close_resource,
)
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterator
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter

    from riko.definitions._resource_definition import Resource
    from riko.types._resource import Cleanup
    from riko.types._sentinels import MissingType
    from riko.types._streams import AnyIterable
    from riko.types._wrappers import (
        AnyModuleWrapper,
        AsyncFunc,
        AsyncModuleWrapperOutput,
        SyncModuleWrapper,
    )

    from ._prepared import ExecutionPlan, PreparedNode


@overload
def _bridge_inputs[T](  # noqa: E704
    extra: Mapping[str, AsyncIterable[T] | Iterator[T]],
) -> Mapping[str, Iterator[T]]: ...
@overload  # noqa: E302
def _bridge_inputs[T](  # noqa: E704
    extra: Mapping[str, ExtraObjects[T]],
) -> Mapping[str, ExtraObjects[T]]: ...
@overload  # noqa: E302
def _bridge_inputs[T](  # noqa: E704
    extra: Mapping[str, list[AsyncIterable[T]] | Iterable[Iterator[T]]],
) -> Mapping[str, Iterable[Iterator[T]]]: ...
@overload  # noqa: E302
def _bridge_inputs[T](  # noqa: E704
    extra: ExtraInput[T],
) -> Mapping[str, ExtraObjects[T] | Iterator[T] | Iterable[Iterator[T]]]: ...
def _bridge_inputs[T](  # noqa: E302
    extra: ExtraInput[T],
) -> Mapping[str, ExtraObjects[T] | Iterator[T] | Iterable[Iterator[T]]]:
    """
    Re-exposes a worker-run node's async input streams as lazy synchronous ones.

    Args:

        extra: The secondary input streams wired for the node, mixed with the non-stream
            values a node may also receive.

    Returns:

        The same mapping with every async stream replaced by a lazy synchronous
        stream over it, and every other value left as it is.

    """
    bridged: dict[str, ExtraObjects | Iterator[T] | Iterable[Iterator[T]]] = {}

    for key, value in extra.items():
        if isinstance(value, AsyncIterable):
            bridged[key] = async_drain(value, run_from_thread)
        elif isinstance(value, list):
            _bridged = (_bridge_inputs({key: v}).values() for v in value)
            bridged[key] = list(chain.from_iterable(_bridged))
        else:
            bridged[key] = value

    return bridged


def _is_owned_teardown_async[T](
    cleanup: Cleanup[T] | Literal[False] | None, value: object
) -> bool:
    """An owned value tears down asynchronously via an async cleanup or ``aclose``."""
    if cleanup is None:
        native_async = _is_async_only_closeable(value)
    else:
        native_async = is_async_callable(cleanup)

    return native_async


@define(eq=False)
class _WorkerContext[T]:
    """Runs a blocking sync context manager's entry and exit on a worker thread."""

    _run: AsyncFunc[T]
    _cm: AbstractContextManager[T]

    async def __aenter__(self) -> T:
        return await self._run(self._cm.__enter__)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return bool(await self._run(self._cm.__exit__, exc_type, exc, traceback))


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
    _budget: Semaphore | None = field(default=None, init=False)
    _node_limiter: Limiter | None = field(default=None, init=False)

    @cached_property
    def _policy(self) -> AsyncPolicy:
        return resolve_async_policy(self.settings)

    async def __aenter__(self) -> Self:
        return self

    async def _unwind(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> tuple[BaseException | None, bool]:
        """
        Unwinds the exit stack behind a cancellation shield within the budget.

        Returns the exception a native context manager replaced the primary error
        with, if any, and whether the primary error was suppressed. Exhausting the
        shutdown budget is recorded as a cleanup failure rather than replacing the
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

    def callback(self, func: Callable, *args: object) -> None:
        """
        Registers a synchronous ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(self._record_cleanup_error, func, *args)

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

    def _reserve_node_threads(
        self, plan: ExecutionPlan, required: Iterable[str]
    ) -> None:
        """
        Sizes the node-thread limiter so every sync-only node can hold a thread.

        A sync-only node holds one thread while pulling upstream. A chain of nodes
        needs their threads up front. Since the limiter never shrinks, allocate one
        extra thread per node on the plan.

        Args:

            plan: The prepared workflow about to run.
            required: The node ids the selected workflow output runs.

        """
        modules = (plan.nodes[node_id].module for node_id in required)
        sync_nodes = sum(
            not module.is_async_pipe(module.select_async()) for module in modules
        )
        tokens = current_default_thread_limiter().total_tokens + sync_nodes

        if (limiter := self._node_limiter) is None:
            self._node_limiter = CapacityLimiter(tokens)
        else:
            limiter.total_tokens = max(limiter.total_tokens, tokens)

    async def _run_node_call[R](self, func: Callable[..., R], *args: object) -> R:
        """Runs a sync-only node's blocking step on a node thread."""
        self._require_open("run work in")
        return await asyncify(func, limiter=self._node_limiter)(*args)

    def _register_teardown(
        self, teardown: Callable, value: object, *, is_async: bool
    ) -> None:
        """Registers ``teardown(value)`` on unwind: on the loop, or a worker if sync."""
        if is_async:
            self.push_async_callback(teardown, value)
        else:
            self.push_async_callback(_asyncify_call, teardown, value)

    async def _acall_factory[R](self, plan: _ResourcePlan[R]) -> R | Awaitable[R]:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")

        if is_async_callable(factory):
            value = await factory(*plan.args, **plan.kwargs)
        else:
            value = await _asyncify_call(partial(factory, *plan.args, **plan.kwargs))

        if (cleanup := plan.cleanup) not in (None, False):
            self._register_teardown(cleanup, value, is_async=is_async_callable(cleanup))

        return value

    async def _aenter_lifecycle[R](self, plan: _ResourcePlan[R]) -> R:
        if plan.native_async:
            cm = cast("AbstractAsyncContextManager[R]", plan.context_manager)
        else:
            _cm = cast("AbstractContextManager[R]", plan.context_manager)
            cm = _WorkerContext(_asyncify_call, _cm)

        return await self.enter_async_context(cm)

    async def _aopen[R](self, plan: _ResourcePlan[R]) -> R | MissingType | Awaitable[R]:
        if plan.strategy is _ResourceStrategy.EXTERNAL:
            value = plan.value
        elif plan.strategy is _ResourceStrategy.OWNED:
            value = plan.value
            is_async = _is_owned_teardown_async(plan.cleanup, value)
            close = aclose_resource if is_async else close_resource
            teardown = partial(close, plan.cleanup)
            self._register_teardown(teardown, value, is_async=is_async)
        elif plan.strategy is _ResourceStrategy.VALUE_FACTORY:
            value = await self._acall_factory(plan)
        else:
            value = await self._aenter_lifecycle(plan)

        return value

    async def _aacquire_entry[R](self, resource: Resource[R]) -> Acquisition:
        plan = build_resource_plan(resource)

        try:
            value = await self._aopen(plan)
        except Exception as error:  # noqa: BLE001
            entry: Acquisition = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    async def _acquire_entry_once[R](self, resource: Resource[R]) -> Acquisition:
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

        if isinstance(entry, _FailedAcquisition):
            raise entry.error

        return cast("R", entry.value)

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
        self,
        pipe: AnyModuleWrapper,
        node: PreparedNode,
        extra: ExtraInput,
        policy: AsyncPolicy,
    ) -> Callable[[T], Awaitable[Iterable[T]]]:
        """
        Binds a mapped node's pipe into a call that collects one item's results.

        A synchronous pipe runs on a worker thread, or on the event-loop thread
        when the settings choose the inline executor.
        """
        prepared = node.select_call(pipe)

        if node.module.is_async_pipe(pipe):

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
            kwargs = _bridge_inputs(extra)
            bound = partial(prepared, context=self.context, **kwargs)
            sync_call = cast("Callable[[T], Iterable[T]]", bound)

            async def call_adapted(item: T) -> Iterable[T]:
                if policy.inline:
                    results = run_item(sync_call, item)
                else:
                    results = await self.run_sync(run_item, sync_call, item)

                return results

            call = call_adapted

        return call

    async def _amap_stream(
        self,
        call: Callable[[T], Awaitable[Iterable[T]]],
        source: AsyncIterable[T],
        limit: int,
    ) -> AsyncIterator[T]:
        """
        Maps a bound call over a node's items under the run's shared ceiling.

        Closing the stream early stops its in-flight calls in the consuming task.
        """
        if self._budget is None:
            self._budget = Semaphore(limit)

        mapper = async_map_ordered_stream if self.settings.ordered else async_map_stream
        mapped = mapper(call, source, limit=limit, buffer=0, budget=self._budget)

        async with aclosing(mapped) as results:
            async for result in results:
                for item in result:
                    yield item

    async def _run_sync_node(
        self,
        pipe: SyncModuleWrapper,
        node: PreparedNode,
        source: AsyncIterable[T],
        extra: ExtraInput,
    ) -> AsyncIterator[T]:
        """
        Streams a sync-only node's output stream without materializing it.

        The pipe runs on a worker thread, reads its async input streams lazily from
        there, and that stream is pulled one item at a time as the consumer asks
        for it.

        Args:

            pipe: The node's synchronous pipe.
            node: The prepared node being run.
            source: The node's primary async input stream.
            extra: The node's secondary input streams and non-stream arguments.

        Returns:

            The async item stream produced by the node.

        """
        bridged = _bridge_inputs(extra)
        worker_source = async_drain(source, run_from_thread)
        call = node.select_call(pipe)

        def start() -> tuple[object, Iterator[T]]:
            raw = call(worker_source, context=self.context, **bridged)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            return raw, require_stream(value, pipe)

        raw, iterator = await self._run_node_call(start)
        return pull_stream(iterator, raw, self._run_node_call, _asyncify_call)

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: AsyncExecSteps,
        seed: AnyIterable[T] | None,
        policy: AsyncPolicy,
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
            policy: The run's resolved concurrency policy.

        Returns:

            The node's lazy async output stream.

        """
        node = plan.nodes[node_id]
        pipe = node.module.select_async()
        host_isasync = node.module.is_async_pipe(pipe)
        args = (node.incoming, steps, seed)
        source, extra = self._resolve_node_inputs(*args, as_stream=as_async)

        if node.resources:
            extra["resources"] = await self._abind_resources(node.resources)

        if (embed := node.embed) is not None:
            drain = partial(async_drain, call=run_from_thread)
            extra["embed"] = select_embed(
                embed, host_isasync=host_isasync, run_sync=self.run_sync, drain=drain
            )

        limit = policy.limit

        if limit is not None and is_mappable(node, extra):
            call = self._build_item_call(pipe, node, extra, policy)
            stream = self._amap_stream(call, source, limit)
        elif not node.module.is_async_pipe(pipe):
            stream = await self._run_sync_node(pipe, node, source, extra)
        else:
            call = node.select_call(pipe)
            _stream = call(source, context=self.context, **extra)
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = require_async_stream(value, pipe)

        return stream

    async def _arun_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> AsyncIterator[T]:
        """Builds the async item stream for one of the plan's workflow outputs."""
        policy = self._policy

        endpoint, required = plan.require_output(output)
        steps: AsyncExecSteps = {}
        self._reserve_node_threads(plan, required)
        seed = None if source is None else await self._abuild_source_stream(source)

        for node_id, node_seed in self._gen_build_order(plan, required, seed):
            args = (plan, node_id, steps, node_seed, policy)
            steps[node_id] = await self._abuild_stream(*args)

        return steps[endpoint.node]

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
                the workflow output has no single open input, or if the settings name
                the process executor.

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
