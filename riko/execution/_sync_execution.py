# vim: sw=4:ts=4:expandtab
"""
Private synchronous execution that runs a prepared workflow.

It owns one exit stack for a run's acquired resources, a lazily started blocking
portal for async-only components, and the run's one worker pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack
from functools import cached_property, partial
from inspect import isawaitable
from multiprocessing import Pool as CPUPool
from multiprocessing.dummy import Pool as ThreadPool
from typing import TYPE_CHECKING, Self, cast, overload

from attrs import define, field

from riko.bado._backend import start_blocking_portal
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.types._enums import Executor
from riko.types._resource import ResourceStrategy

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
    _asyncify_call,
    _BaseExecution,
    _FailedAcquisition,
    _require_source,
)
from ._pools import _PoolLifetime
from ._resource_plan import _ResourcePlan, close_resource
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from contextlib import AbstractContextManager
    from types import TracebackType

    from anyio.from_thread import BlockingPortal

    from riko.definitions._resource_definition import ResolvedValue, Resource
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
        >>> from riko.execution import SyncExecution
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

    def __enter__(self) -> Self:
        return self

    @cached_property
    def _pool(self) -> _PoolLifetime:
        """The run's one worker pool, shared by every mapped node."""
        executor, workers = self.settings.sync_policy

        if workers is None:
            action = "open a worker pool in"
            raise PipelineStateError("sequential", action, subject="execution")

        pool = ThreadPool(workers) if executor is Executor.THREAD else CPUPool(workers)
        return self._stack.enter_context(_PoolLifetime(pool, workers))

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        """
        Unwinds the exit stack and stops the portal under the primary error.

        Only the first call shuts the execution down. A repeated call does nothing.
        """
        suppressed = False

        if not self._closing:
            self._closing = True
            raised: BaseException | None = None

            try:
                suppressed = bool(self._stack.__exit__(exc_type, exc, traceback))
            except Exception as error:  # noqa: BLE001
                raised = error

            self._report_shutdown(exc, raised, suppressed)

        return suppressed

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return self.close(exc_type, exc, traceback)

    @cached_property
    def portal(self) -> BlockingPortal:
        if (portal_cm := start_blocking_portal()) is None:
            msg = "anyio is required to run async components in a sync execution"
            raise RuntimeError(msg)

        return self.enter_context(portal_cm)

    @overload
    def run_async[R](self, func: Awaitable[R], /) -> R: ...  # noqa: E704
    @overload  # noqa: E301
    def run_async[R](  # noqa: E704
        self, func: Callable[..., Awaitable[R]], /, *args: object
    ) -> R: ...
    def run_async[R](  # noqa: E301
        self, func: Awaitable[R] | Callable[..., Awaitable[R]], *args: object
    ) -> R:
        """
        Runs async work to completion through the execution portal.

        A callable is invoked on the portal loop and its awaitable result awaited;
        a bare awaitable is deferred through a thunk, since the portal takes a
        callable rather than an awaitable.

        Args:

            func: An async callable to invoke on the portal loop, or an awaitable
                to await directly.
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

    def _validate_sync_teardown[R](self, plan: _ResourcePlan[R]) -> None:
        if plan.is_teardown_async:
            if plan.strategy is ResourceStrategy.LIFECYCLE:
                msg = "async-native resource lifecycle requires async execution"
            elif plan.cleanup is None:
                msg = "async-native resource teardown requires async execution"
            else:
                msg = "async resource cleanup requires async execution"

            raise InvalidPipelineError(msg)

    def _call_factory[R](self, plan: _ResourcePlan[R]) -> R:
        raw = plan.call_factory()
        value = self.run_async(raw) if isawaitable(raw) else cast("R", raw)

        if cleanup := plan.cleanup:
            self.callback(cleanup, value)

        return value

    def _enter_lifecycle[R](self, plan: _ResourcePlan[R]) -> R:
        cm = cast("AbstractContextManager[R]", plan.build_context_manager())
        return self.enter_context(cm)

    def _open[R](self, plan: _ResourcePlan[R]) -> ResolvedValue[R]:
        self._validate_sync_teardown(plan)

        if plan.strategy is ResourceStrategy.EXTERNAL:
            value = plan.value
        elif plan.strategy is ResourceStrategy.OWNED:
            value = plan.value
            self.callback(close_resource, plan.cleanup, value)
        elif plan.strategy is ResourceStrategy.VALUE_FACTORY:
            value = self._call_factory(plan)
        else:
            value = self._enter_lifecycle(plan)

        return value

    def _acquire_entry[R](self, resource: Resource[R]) -> Acquisition[ResolvedValue[R]]:
        try:
            value = self._open(_ResourcePlan(resource))
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

    def _async_drain(self, source: AsyncIterable[T]) -> Iterator[T]:
        """Pulls an async stream item by item through the execution portal."""
        return async_drain(source, self.run_async)

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        pairs = self._require_bindings(binding).items()
        return ResourceView({slot: self.acquire(resource) for slot, resource in pairs})

    def _map_stream(
        self, call: Callable[[T], Iterable[T]], source: Iterator[T]
    ) -> Iterator[T]:
        """Maps a bound pipe over its items once the consumer first pulls."""
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
        sync_native = node.sync_interface.native
        call, pipe = node.sync_interface.call, node.sync_interface.pipe
        args = (node.incoming, steps, seed)
        source, extra = self._resolve_node_inputs(*args, as_stream=iter)

        if node.resources:
            extra["resources"] = self._bind_resources(node.resources)

        if (embed := node.embed) is not None:
            host_isasync, drain = not sync_native, self._async_drain
            extra["embed"] = select_embed(
                embed, host_isasync=host_isasync, run_sync=_asyncify_call, drain=drain
            )

        if self.settings.sync_policy.workers is not None and node.is_sync_mappable:
            bound = partial(call, context=self.context, **extra)
            stream = self._map_stream(cast("Callable[[T], Iterable[T]]", bound), source)
        elif sync_native:
            _stream = call(source, context=self.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", _stream)
            stream = require_stream(value, pipe)
        else:
            _stream = call(source, context=self.context, **extra)
            avalue = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = self._async_drain(require_async_stream(avalue, pipe))

        return stream

    def _build_source_stream(
        self, value: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]]
    ) -> Iterator[T]:
        """Resolves a seed of any accepted shape to one lazy item stream."""
        resolved = self.run_async(value) if isawaitable(value) else value

        if isinstance(resolved, AsyncIterable):
            stream = self._async_drain(resolved)
        else:
            stream = iter(normalize_items(resolved))

        return stream

    def _run_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> Iterator[T]:
        """Builds the item stream for one of the plan's workflow outputs."""
        endpoint = plan.require_output(output)
        steps: SyncExecSteps = {}

        if self.settings.sync_policy.executor is Executor.PROCESS:
            require_process_safe(plan, output, self.context)

        seed = None if source is None else self._build_source_stream(source)

        for node_id, node_seed in plan.gen_build_order(output, seed=seed):
            steps[node_id] = self._build_stream(plan, node_id, steps, node_seed)

        return steps[endpoint.node]

    def run(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> Iterator[T]:
        """
        Builds the item stream for one of the plan's workflow outputs.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``with`` block so its teardown stays
        owned.

        Args:

            plan: The prepared workflow to run.

            output: The name of the workflow output to produce.

            source: A seed for the workflow output's open input in place of the
                default empty seed. It can be one item, an item stream, an async item
                stream, or an awaitable resolving to one of those. When omitted, only a
                node with no default or positional input port receives that default. A
                plan with no nodes streams it unchanged as its default output.

        Returns:

            The item stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If the plan exposes no such workflow output, if it
                has no nodes and no ``source`` is given, if ``source`` is supplied but
                the workflow output has no single open input, or if the process executor
                is chosen and a node cannot be sent to a worker process.

        """
        self._require_open("run")

        if plan.workflow.is_empty:
            stream = self._build_source_stream(_require_source(source, output))
        else:
            stream = self._run_plan(plan, output, source)

        return stream


__all__ = ["SyncExecution"]
