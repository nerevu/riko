# vim: sw=4:ts=4:expandtab
"""
Private synchronous execution that runs a prepared workflow.

It owns one exit stack for a run's acquired resources, a lazily started blocking
portal for async-only components, and the run's one worker pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Iterator, Mapping
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import ExitStack
from functools import cached_property, partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Literal, Self, cast, overload

from attrs import define, field

from riko.bado._backend import fail_after, start_blocking_portal
from riko.bado._util import run_bridged
from riko.base._config import DEFAULT_OUTPUT
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._funcutils import map_values
from riko.base._guards import is_async_callable, is_awaitable
from riko.definitions._nodes import CallableNode
from riko.types._enums import Executor
from riko.types._io import ASYNC_CLEANUP_MSG, resolve_closer
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
    require_async_stream,
    require_stream,
    select_embed,
)
from ._concurrency import build_item_call, require_process_safe
from ._execution import (
    Acquisition,
    SyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._pools import _PoolLifetime
from ._prepared import ExecutionExtras
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from anyio.from_thread import BlockingPortal

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import AnyIterable
    from riko.types._wrappers import AsyncFunc, AsyncModuleWrapperOutput

    from ._prepared import ExecutionPlan


@define(eq=False)
class _BoundedExit[T]:
    """Exits an async context manager within a timeout and records its expiry."""

    _cm: AbstractAsyncContextManager[T]
    _timeout: float
    _errors: list[Exception]

    async def __aenter__(self) -> T:
        return await self._cm.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        raised: BaseException | None = None
        suppressed = False

        try:
            with fail_after(self._timeout):
                try:
                    _suppressed = await self._cm.__aexit__(exc_type, exc, traceback)
                    suppressed = bool(_suppressed)
                except Exception as error:  # noqa: BLE001
                    raised = error
        except TimeoutError as error:
            self._errors.append(error)

        if raised is not None:
            raise raised

        return suppressed


@define(eq=False)
class SyncExecution[T](_BaseExecution[ExitStack]):
    """
    Runs a prepared workflow synchronously behind one owned exit stack.

    Async-only components run through a lazily started blocking portal. The
    execution settings decide whether loopable nodes spread their items across
    one shared thread or process pool for the run.

    Examples:

        >>> from contextlib import contextmanager
        >>> from riko.execution._sync_execution import SyncExecution
        >>>
        >>> events = []
        >>> @contextmanager
        ... def track(name):
        ...     events.append(f"open {name}")
        ...     yield name
        ...     events.append(f"close {name}")
        >>>
        >>> with SyncExecution() as execution:
        ...     first = execution.enter_context(track("a"))
        ...     second = execution.enter_context(track("b"))
        ...     (first, second)
        ('a', 'b')
        >>> events
        ['open a', 'open b', 'close b', 'close a']

    """

    _stack: ExitStack = field(factory=ExitStack, init=False)
    _pools: ExitStack = field(factory=ExitStack, init=False)

    @cached_property
    def _pool(self) -> _PoolLifetime:
        """The run's one worker pool, shared by every mapped node."""
        executor, workers = self.settings.sync_policy

        if workers is None:
            action = "open a worker pool in"
            raise PipelineStateError("sequential", action, subject="execution")

        pool_type = (
            ThreadPoolExecutor if executor is Executor.THREAD else ProcessPoolExecutor
        )
        pool = pool_type(workers)
        grace = self.settings.shutdown_timeout
        return self._pools.enter_context(_PoolLifetime(pool, workers, grace=grace))

    @cached_property
    def portal(self) -> BlockingPortal:
        if (portal_cm := start_blocking_portal()) is None:
            msg = "anyio is required to run async components in a sync execution"
            raise RuntimeError(msg)

        return self.enter_context(portal_cm)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return self.close(exc_type, exc, traceback)

    def _async_drain(self, items: AsyncIterable[T]) -> Iterator[T]:
        """Pulls an async stream item by item through the execution portal."""
        return async_drain(items, self.run_async)

    def _drain_owned(self, items: AsyncIterable[T]) -> Iterator[T]:
        """Drains an async stream this execution owns and closes it at exit."""
        self.register_owned(items, is_async=True)
        return self._async_drain(items)

    @overload
    def run_async[R](self, func: Awaitable[R], /) -> R: ...
    @overload
    def run_async[R](self, func: AsyncFunc[R], /, *args: object) -> R: ...
    def run_async[R](self, func: Awaitable[R] | AsyncFunc[R], *args: object) -> R:
        """
        Runs async work to completion through the execution portal.

        A callable is invoked on the portal loop and its awaitable result awaited;
        a bare awaitable is deferred through a thunk, since the portal takes a
        callable rather than an awaitable.

        Args:

            func: An async callable to invoke on the portal loop, or an awaitable to
                await directly.

            args: Positional arguments forwarded to a callable ``func``.

        Returns:

            The value the awaited work resolves to.

        """
        self._require_open("run work in")

        if isawaitable(func):
            result = self.portal.call(lambda: func)
        else:
            result = self.portal.call(func, *args)

        return result

    async def _await_bounded(self, value: Awaitable[object]) -> object:
        """Awaits ``value`` within the shutdown timeout."""
        with fail_after(self.settings.shutdown_timeout):
            return await value

    def _run_bounded(self, portal: BlockingPortal, value: Awaitable[object]) -> object:
        """Runs ``value`` on ``portal``'s loop within the shutdown timeout."""
        return portal.call(self._await_bounded, value)

    def register_owned[R](
        self,
        value: R,
        cleanup: Cleanup[R] | Literal[False] | None = None,
        *,
        is_async: bool = False,
    ) -> None:
        """
        Registers an owned value to close when the execution exits.

        Args:

            value: The value to close.

        Kwargs:

            cleanup: The cleanup to call with ``value`` in place of its own close, or
                ``False`` to leave it open.

            is_async: Whether ``value`` was produced on the execution's event loop, so
                its async close or cleanup runs there within the shutdown timeout.

        Raises:

            InvalidPipelineError: If ``is_async`` is unset and ``value``'s only
                close, or its ``cleanup``, is async.

        """
        if (closer := resolve_closer(value, cleanup, is_async=is_async)) is not None:
            bridge = partial(self._run_bounded, self.portal) if is_async else None
            self.queue_callback(run_bridged, closer, bridge)

    def _call_factory[R](self, plan: ValueFactoryPlan[R]) -> R:
        if not plan.is_async and is_async_callable(plan.cleanup):
            raise InvalidPipelineError(ASYNC_CLEANUP_MSG)

        raw = call_factory(plan)
        value = self.run_async(raw) if is_awaitable(raw) else raw
        self.register_owned(value, plan.cleanup, is_async=plan.is_async)
        return value

    def _enter_lifecycle[R](self, plan: SyncLifecyclePlan[R]) -> R:
        return self.enter_context(build_context_manager(plan))

    def _enter_async_lifecycle[R](self, plan: AsyncLifecyclePlan[R]) -> R:
        timeout = self.settings.shutdown_timeout
        cm = _BoundedExit(build_context_manager(plan), timeout, self._cleanup_errors)
        return self.enter_context(self.portal.wrap_async_context_manager(cm))

    def _open[R](self, plan: ResourcePlan[R]) -> R:
        match plan:
            case ExternalPlan():
                value = plan.value
            case OwnedPlan():
                value = plan.value
                self.register_owned(value, plan.cleanup)
            case ValueFactoryPlan():
                value = self._call_factory(plan)
            case SyncLifecyclePlan():
                value = self._enter_lifecycle(plan)
            case AsyncLifecyclePlan():
                value = self._enter_async_lifecycle(plan)

        return value

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        """
        Unwinds the exit stack and stops the portal under the primary error.

        The worker pool is released first, so no worker still runs when resources close.
        Only the first call shuts the execution down. A repeated call does nothing.
        """
        suppressed = False

        if not self._closing:
            self._closing = True
            raised: BaseException | None = None
            self._stack.push(self._pools)

            try:
                suppressed = bool(self._stack.__exit__(exc_type, exc, traceback))
            except Exception as error:  # noqa: BLE001
                raised = error

            self._report_shutdown(exc, raised, suppressed)

        return suppressed

    def _acquire_entry[R](self, resource: Resource[R]) -> Acquisition[R]:
        try:
            value = self._open(resource._plan)
        except Exception as error:  # noqa: BLE001
            entry: Acquisition[R] = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    def acquire[R](self, resource: Resource[R]) -> R:
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

        if resource not in self._acquired:
            self._acquired[resource] = self._acquire_entry(resource)

        return self._acquired[resource].unwrap()

    def _open_seed(
        self, seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]]
    ) -> Iterator[T]:
        """
        Opens a seed as the item stream this execution reads.

        A seed is one item, an item stream, an async item stream, or an awaitable
        resolving to one of those. An awaitable is awaited when the run starts. The
        stream stays lazy. A seed that is both sync- and async-iterable is read
        synchronously. The execution closes a seed with ``close``, or any async seed
        with ``aclose``, when it exits. A seed read synchronously whose only close is
        async raises ``InvalidPipelineError`` before any item is read.
        """
        resolved = self.run_async(seed) if is_awaitable(seed) else seed

        if isinstance(resolved, Iterable) or not isinstance(resolved, AsyncIterable):
            self.register_owned(resolved)
            stream = iter(normalize_items(resolved))
        else:
            stream = self._drain_owned(resolved)

        return stream

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        return ResourceView(map_values(self.acquire, self._require_bindings(binding)))

    def _map_stream(
        self, call: Callable[[T], Iterable[T]], source: Iterator[T]
    ) -> Iterator[T]:
        """Maps a prepared pipe over its items once the consumer first pulls."""
        self._require_open("map items in")
        func = build_item_call(call, self.settings.sync_policy.executor)
        yield from self._pool.flat_map(func, source, ordered=self.settings.ordered)

    def _build_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: SyncExecSteps[T],
        seed: Iterable[T] | None = None,
        *,
        context: Context | None,
    ) -> Iterator[T]:
        """
        Builds one node's lazy output stream from its already-built input streams.

        When the settings allow concurrency, a loopable node with a synchronous
        implementation and no secondary input stream runs its items across the run's
        worker pool. Concurrency applies to synchronous pipes here. Iterate
        asynchronously for concurrent async work.

        Args:

            plan: The prepared workflow being run.
            node_id: The node to build.
            steps: The streams already built for upstream nodes.

        Kwargs:

            seed: The items fed to the node's open input, if any.
            context: The run's context with its resolved input values.

        Returns:

            The node's lazy output stream.

        """
        node = plan.nodes[node_id]
        interface = node.sync_interface
        native = interface.native
        args = (node.incoming, steps, seed)
        _stream, named, others = self._resolve_node_inputs(*args, as_stream=iter)
        bind = self._bind_resources
        resources = bind(node.resources) if node.resources else None

        if node.embed is None:
            embed = None
        else:
            embed = select_embed(
                node.embed,
                host_isasync=not native,
                run_sync=self.run_sync,
                drain=self._async_drain,
            )

        extras = ExecutionExtras(others=others, resources=resources, embed=embed)
        extra = {**named, **extras.kwargs}

        if self.settings.sync_policy.workers is not None and node.is_sync_mappable:
            callable_context = None if isinstance(node.node, CallableNode) else context
            # a local mapped closure fails pickling
            _mapped = partial(interface.item_call, context=callable_context, **extra)
            mapped = cast("Callable[[T], Iterable[T]]", _mapped)
            stream = self._map_stream(mapped, _stream)
        elif native:
            _stream = interface.call(_stream, context=context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", _stream)
            stream = require_stream(value, interface.pipe)

            if value is not stream:
                self.register_owned(value)
        else:
            _stream = interface.call(_stream, context=context, **extra)
            avalue = cast("AsyncModuleWrapperOutput[T]", _stream)
            astream = require_async_stream(avalue, interface.pipe)

            if avalue is not astream:
                self.register_owned(avalue, is_async=True)

            stream = self._drain_owned(astream)

        return stream

    def _run_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
        context: Context | None,
    ) -> Iterator[T]:
        """
        Builds the item stream for one of the plan's workflow outputs.

        The execution closes every node stream it built when it exits, last built
        first. It closes even when building a later node fails, and then any closeable
        value a pipe returned in place of its stream. The output stream is the caller's
        to close.
        """
        endpoint = plan.require_output(output)
        steps: SyncExecSteps[T] = {}

        if self.settings.sync_policy.executor is Executor.PROCESS:
            require_process_safe(plan, output, context)

        stream = None if seed is None else self._open_seed(seed)

        for node_id, node_seed in plan.gen_build_order(output, seed=stream):
            args = (plan, node_id, steps, node_seed)
            node_stream = self._build_stream(*args, context=context)
            steps[node_id] = node_stream

            if node_id != endpoint.node:
                self.register_owned(node_stream)

        return steps[endpoint.node]

    def run(
        self,
        plan: ExecutionPlan,
        output: str = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> Iterator[T]:
        """
        Builds the item stream for one of the plan's workflow outputs.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``with`` block so its cleanup stays
        owned.

        Args:

            plan: The prepared workflow to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input. It can be one item, an
                item stream, an async item stream, or an awaitable resolving to one of
                those.

                When omitted, every node must either be self-starting or receive a seed.
                A plan with no nodes streams the seed back unchanged.

        Returns:

            The item stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If ``output`` is not exposed by ``plan``; if ``seed``
                isn't given and a node requires one, or the plan has no nodes; if
                ``seed`` is given but the ``plan``'s ``output`` doesn't have exactly one
                node for it to feed; if a workflow input is missing or invalid;
                or if the process executor is chosen and a node cannot be sent to a
                worker process.

        """
        self._require_open("run")
        resolved, context = self._resolve_plan(plan)

        if resolved.workflow.is_empty:
            stream = self._open_seed(resolved.require_seed(seed, output))
        else:
            stream = self._run_plan(resolved, output, seed, context)

        return stream


__all__ = ["SyncExecution"]
