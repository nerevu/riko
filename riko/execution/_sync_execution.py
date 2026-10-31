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
from typing import TYPE_CHECKING, Self, cast, overload

from attrs import define, field

from riko.bado._backend import start_blocking_portal
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._guards import is_awaitable
from riko.base._iterutils import map_values
from riko.definitions._nodes import CallableNode
from riko.types._enums import Executor
from riko.types._io import is_async_closeable, is_sync_closeable
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
    asyncify_call,
)
from ._pools import _PoolLifetime
from ._prepared import ExecutionExtras
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_cleanup import close_resource, close_with
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from types import TracebackType

    from anyio.from_thread import BlockingPortal

    from riko.definitions._resource_definition import Resource
    from riko.types._resource import ResolvedValue, ResourcePlan
    from riko.types._streams import AnyIterable
    from riko.types._wrappers import AsyncModuleWrapperOutput

    from ._prepared import ExecutionPlan


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
        if is_async_closeable(items):
            self.queue_callback(self.portal.call, items.aclose)

        return self._async_drain(items)

    @overload
    def run_async[R](self, func: Awaitable[R], /) -> R: ...
    @overload
    def run_async[R](
        self, func: Callable[..., Awaitable[R]], /, *args: object
    ) -> R: ...
    def run_async[R](
        self, func: Awaitable[R] | Callable[..., Awaitable[R]], *args: object
    ) -> R:
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

    def _register_cleanup(self, cleanup: Callable, value: object) -> None:
        """Registers ``cleanup(value)`` to run on unwind."""
        self.queue_callback(close_with, cleanup, value)

    def _validate_cleanup[R](self, plan: OwnedPlan[R] | ValueFactoryPlan[R]) -> None:
        if plan.requires_async_cleanup:
            match plan:
                case OwnedPlan(cleanup=None):
                    msg = "closing an async-only resource requires async execution"
                case _:
                    msg = "async resource cleanup requires async execution"

            raise InvalidPipelineError(msg)

    def _call_factory[R](self, plan: ValueFactoryPlan[R]) -> R:
        raw = call_factory(plan)
        value = self.run_async(raw) if is_awaitable(raw) else raw

        if (cleanup := plan.cleanup) is not False:
            self._register_cleanup(cleanup, value)

        return value

    def _enter_lifecycle[R](self, plan: SyncLifecyclePlan[R]) -> R:
        return self.enter_context(build_context_manager(plan))

    def _open[R](self, plan: ResourcePlan[R]) -> ResolvedValue[R]:
        match plan:
            case ExternalPlan():
                value = plan.value
            case OwnedPlan():
                value = plan.value
                self._validate_cleanup(plan)
                cleanup = partial(close_resource, plan.cleanup)
                self._register_cleanup(cleanup, value)
            case ValueFactoryPlan():
                self._validate_cleanup(plan)
                value = self._call_factory(plan)
            case SyncLifecyclePlan():
                value = self._enter_lifecycle(plan)
            case AsyncLifecyclePlan():
                msg = "async-native resource lifecycle requires async execution"
                raise InvalidPipelineError(msg)

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

    def _acquire_entry[R](self, resource: Resource[R]) -> Acquisition[ResolvedValue[R]]:
        try:
            value = self._open(resource._plan)
        except Exception as error:  # noqa: BLE001
            entry: Acquisition[ResolvedValue[R]] = _FailedAcquisition(error)
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
        resolving to one of those. An awaitable is awaited when the run starts; the
        stream itself stays lazy. A seed that is both sync- and async-iterable is
        read synchronously. The execution closes a seed with ``close``, or any async
        seed with ``aclose``, when it exits.
        """
        resolved = self.run_async(seed) if is_awaitable(seed) else seed

        if isinstance(resolved, Iterable) or not isinstance(resolved, AsyncIterable):
            stream = iter(normalize_items(resolved))
        else:
            stream = self._drain_owned(resolved)

        if is_sync_closeable(resolved):
            self.queue_callback(resolved.close)

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
        steps: SyncExecSteps,
        seed: Iterable[T] | None = None,
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
            seed: The items fed to the node's open input, if any.

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
                run_sync=asyncify_call,
                drain=self._async_drain,
            )

        extras = ExecutionExtras(others=others, resources=resources, embed=embed)
        extra = {**named, **extras.kwargs}

        if self.settings.sync_policy.workers is not None and node.is_sync_mappable:
            call = interface.item_call
            context = None if isinstance(node.node, CallableNode) else self.context
            _mapped = partial(call, context=context, **extra)
            mapped = cast("Callable[[T], Iterable[T]]", _mapped)
            stream = self._map_stream(mapped, _stream)
        elif native:
            _stream = interface.call(_stream, context=self.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", _stream)
            stream = require_stream(value, interface.pipe)
        else:
            _stream = interface.call(_stream, context=self.context, **extra)
            avalue = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = self._drain_owned(require_async_stream(avalue, interface.pipe))

        return stream

    def _run_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> Iterator[T]:
        """
        Builds the item stream for one of the plan's workflow outputs.

        The execution closes every node stream it built when it exits, last built
        first, even when building a later node fails. The output stream is the
        caller's to close.
        """
        endpoint = plan.require_output(output)
        steps: SyncExecSteps = {}

        if self.settings.sync_policy.executor is Executor.PROCESS:
            require_process_safe(plan, output, self.context)

        stream = None if seed is None else self._open_seed(seed)

        for node_id, node_seed in plan.gen_build_order(output, seed=stream):
            node_stream = self._build_stream(plan, node_id, steps, node_seed)
            steps[node_id] = node_stream

            if node_id != endpoint.node and is_sync_closeable(node_stream):
                self.queue_callback(node_stream.close)

        return steps[endpoint.node]

    def run(
        self,
        plan: ExecutionPlan,
        output: str = "default",
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

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input. It can be one item, an
                item stream, an async item stream, or an awaitable resolving to one of
                those. When omitted, every node whose default input port gets no input
                stream must be self-starting (a source module, or a node that only feeds
                named input ports). A plan with no nodes streams the seed unchanged as
                its default output.

        Returns:

            The item stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If ``output`` is not exposed by ``plan``; if ``seed``
                isn't given and a node requires one, or the plan has no nodes; if
                ``seed`` is given but the ``plan``'s ``output`` doesn't have exactly one
                node for it to feed; or if the process executor is chosen and a node
                cannot be sent to a worker process.

        """
        self._require_open("run")

        if plan.workflow.is_empty:
            stream = self._open_seed(plan.require_seed(seed, output))
        else:
            stream = self._run_plan(plan, output, seed)

        return stream


__all__ = ["SyncExecution"]
