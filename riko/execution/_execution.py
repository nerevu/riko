# vim: sw=4:ts=4:expandtab
"""
Private sync/async executions that run a prepared workflow.

A prepared workflow (an execution plan) is a reusable structural snapshot; running
it creates one of these one-shot executions. Each owns the exit stack and sync/async
bridge that bound a run's acquired resources and adapted work. These
types are private to the runtime and belong to no supported surface.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Callable,
    Iterable,
    Iterator,
    Mapping,
)
from contextlib import AsyncExitStack, ExitStack, aclosing, nullcontext
from functools import cached_property, partial
from inspect import isawaitable
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
    start_blocking_portal,
)
from riko.bado._util import as_awaitable
from riko.bado.itertools import as_async, async_map_ordered_stream, async_map_stream
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.definitions._execution import DEF_EXECUTION_SETTINGS, ExecutionSettings
from riko.types._compiler import ModuleOptionValues
from riko.types._enums import Executor
from riko.types._guards import is_async_callable
from riko.types._io import is_async_closeable, is_sync_closeable
from riko.types._workflow import parse_port
from riko.types._wrappers import AsyncModuleWrapperOutput, ModuleWrapper

from ._adapt import (
    async_drain,
    normalize_items,
    pull_stream,
    require_async_stream,
    require_stream,
    select_embed,
)
from ._events import _NULL_EVENT_SINK
from ._mapping import (
    AsyncPolicy,
    SyncPolicy,
    _PoolLifetime,
    is_mappable,
    require_process_safe,
    resolve_async_policy,
    resolve_sync_policy,
    run_item,
)
from ._pools import open_pool
from ._resource_plan import (
    _ResourcePlan,
    _ResourceStrategy,
    aclose_resource,
    build_resource_plan,
    close_resource,
)
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.from_thread import BlockingPortal

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._events import EventSink
    from riko.types._resource import Cleanup
    from riko.types._sentinels import MissingType
    from riko.types._streams import AnyIterable, Item
    from riko.types._workflow import Endpoint, GraphEdge
    from riko.types._wrappers import AnyModuleWrapper, AsyncFunc, SyncModuleWrapper

    from ._prepared import ExecutionPlan, PreparedNode


type SyncExecSteps[T] = dict[str, Iterator[T]]
type AsyncExecSteps[T] = dict[str, AsyncIterator[T]]
type ExtraObjects[T] = ResourceView | ModuleWrapper | ModuleOptionValues
type ExtraStreams[T] = (
    AsyncIterable[T] | list[AsyncIterable[T]] | Iterator[T] | Iterable[Iterator[T]]
)
type ExtraValues[T] = ExtraObjects[T] | ExtraStreams[T]
type ExtraInput[T] = Mapping[str, ExtraValues[T]]
type ExtraOutput[T] = dict[str, ExtraValues[T]]
type Acquisition = _Acquired | _FailedAcquisition
type Acquisitions = dict[Resource[Any], Acquisition]

DEFAULT_SEED: list[Item] = [{"forever": True}]


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


async def _asyncify_call[T](func: Callable[..., T], *args: object) -> T:
    """
    Runs a blocking callable on a worker thread from the current event loop.

    No execution's open check applies, so resource teardown and stream closing can
    still offload work while an execution is shutting down.

    Args:

        func: The blocking callable to offload.
        args: Positional arguments forwarded to ``func``.

    Returns:

        The value ``func`` returns.

    """
    return await asyncify(func)(*args)


def _require_source[S](source: S | None, output: str) -> S:
    """Requires the seed an identity plan streams as its default output."""
    if output != "default":
        raise InvalidPipelineError(f"workflow has no workflow output {output!r}")
    elif source is None:
        msg = "workflow has no nodes; an empty workflow requires a seed"
        raise InvalidPipelineError(msg)

    return source


def _require_seed_target(plan: ExecutionPlan, required: frozenset[str]) -> str:
    """
    Supplies the one node in ``required`` whose default input is open to a seed.

    A node's default input is open when no incoming stream edge targets its bare
    default input port. A seed needs exactly one such node.

    Args:

        plan: The prepared workflow being run.
        required: The node ids that the selected workflow output's subgraph runs.

    Returns:

        The id of the single node whose default input a supplied seed feeds.

    Raises:

        InvalidPipelineError: If the required subgraph has no single open input.

    """
    roots = required.intersection(plan.index.order)
    open_roots = [root for root in roots if plan.index.is_open(root)]

    if (count := len(open_roots)) == 1:
        target = open_roots[0]
    else:
        msg = f"a seed requires exactly one open input, found {count}"
        raise InvalidPipelineError(msg)

    return target


def _require_default_output_port(port: str, ref: str) -> None:
    """
    Rejects a non-default output port until multi-output delivery is executable.

    Only the bare ``out`` port is executable today. A positional ``out:N`` or
    semantic ``out:<name>`` source or selected workflow output is refused rather than
    silently read as the node's default ``out`` stream.

    Args:

        port: The source or selected workflow output's port string to check.
        ref: A human-readable reference to the offending edge or workflow output.

    Raises:

        InvalidPipelineError: If ``port`` is not the default ``out`` port.

    """
    if not parse_port(port).is_default:
        msg = f"{ref} uses the non-default output port {port!r}, which cannot run yet."
        raise InvalidPipelineError(msg)


def _require_output(
    plan: ExecutionPlan, output: str
) -> tuple[Endpoint, frozenset[str]]:
    """Requires a default-port output the plan exposes, with the nodes it runs."""
    if (endpoint := plan.index.outputs.get(output)) is None:
        raise InvalidPipelineError(f"workflow has no workflow output {output!r}")

    _require_default_output_port(endpoint.port, f"workflow output {output!r}")
    return endpoint, plan.index.required[output]


@define(frozen=True, slots=True)
class _Acquired:
    """Holds a successfully acquired resource value for single-flight replay."""

    value: object


@define(frozen=True, slots=True)
class _FailedAcquisition:
    """Holds a failed acquisition so repeated use replays the same error."""

    error: BaseException


def _is_owned_teardown_async[T](
    cleanup: Cleanup[T] | Literal[False] | None, value: object
) -> bool:
    """An owned value tears down asynchronously via an async cleanup or ``aclose``."""
    if cleanup is None:
        native_async = is_async_closeable(value) and not is_sync_closeable(value)
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


def _event_sink(self: _BaseExecution) -> EventSink:
    sink = self.settings.event_sink
    return _NULL_EVENT_SINK if sink is None else sink


events = Factory(_event_sink, takes_self=True)


@define(eq=False)
class _BaseExecution[S: (ExitStack, AsyncExitStack)]:
    """
    Shares the state and checks both executions run without awaiting.

    That covers the context and settings, the closed-state guard, synchronous
    exit-stack entry, cleanup-error reporting, the resolved-resource cache, and
    resource-binding checks.
    """

    context: Context | None = None
    settings: ExecutionSettings = field(default=DEF_EXECUTION_SETTINGS, kw_only=True)
    events: EventSink = field(default=events, kw_only=True)
    _stack: S = field(init=False)
    _closing: bool = field(default=False, init=False)
    _cleanup_errors: list[Exception] = field(factory=list, init=False)
    _acquired: Acquisitions = field(factory=dict, init=False)

    def emit(self, event: object) -> None:
        """
        Dispatches ``event`` to the execution event sink.

        Args:

            event: The event value produced during a run.

        """
        self.events.emit(event)

    def _require_open(self, action: str) -> None:
        if self._closing:
            raise PipelineStateError("closing", action, subject="execution")

    def _record_cleanup_error(self, func: Callable, *args: object) -> None:
        """Runs a cleanup callback and saves its failure for the shutdown report."""
        try:
            func(*args)
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

    @overload
    def enter_context(  # noqa: E704
        self, cm: AbstractContextManager[BlockingPortal]
    ) -> BlockingPortal: ...
    @overload
    def enter_context[V](self, cm: AbstractContextManager[V]) -> V: ...  # noqa: E704
    def enter_context[V](  # noqa: E301
        self, cm: AbstractContextManager[BlockingPortal | V]
    ) -> BlockingPortal | V:
        """
        Enters a synchronous ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

    def _require_bindings(self, binding: Mapping[str, str]) -> dict[str, Resource[Any]]:
        """Requires the context to provide every resource a node binds, by slot."""
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            msg = f"resource(s) {names} not provided by the context"
            raise InvalidPipelineError(msg)

        return {slot: available[name] for slot, name in binding.items()}

    def _report_shutdown(
        self, exc: BaseException | None, raised: BaseException | None, suppressed: bool
    ) -> None:
        """
        Raises the shutdown outcome once cleanup has been attempted in full.

        ``raised`` is an exception that a native context manager replaced the primary
        error with. That replacement, or the unsuppressed primary error, stays the
        primary outcome. Cleanup callback and task failures group alongside it rather
        than replace it. They are raised on their own only when no primary outcome
        remains.
        """
        errors = self._cleanup_errors

        if raised is not None:
            primary: BaseException | None = raised
        elif suppressed:
            primary = None
        else:
            primary = exc

        if not errors and raised is not None:
            raise raised
        elif not errors:
            pass
        elif primary is None and len(errors) == 1:
            raise errors[0]
        elif primary is None:
            raise ExceptionGroup("Execution shutdown failed", errors)
        else:
            raise BaseExceptionGroup("Execution shutdown failed", [primary, *errors])


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
    def _policy(self) -> SyncPolicy:
        return resolve_sync_policy(self.settings)

    @cached_property
    def _pool(self) -> _PoolLifetime:
        """The run's one worker pool, shared by every mapped node."""
        action = "open a worker pool in"

        if (workers := self._policy.workers) is None:
            raise PipelineStateError("sequential", action, subject="execution")

        self._require_open(action)
        handle = open_pool(self._policy.executor, workers)
        return self._stack.enter_context(_PoolLifetime(handle, workers))

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

    def callback(self, func: Callable, *args: object) -> None:
        """
        Registers ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(self._record_cleanup_error, func, *args)

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
        is_lifecycle = plan.strategy is _ResourceStrategy.LIFECYCLE
        native_lifecycle = is_lifecycle and plan.native_async
        cleanup = plan.cleanup

        async_owned_value = (
            plan.strategy is _ResourceStrategy.OWNED
            and cleanup is None
            and is_async_closeable(plan.value)
            and not is_sync_closeable(plan.value)
        )

        if native_lifecycle:
            msg = "async-native resource lifecycle requires async execution"
            raise InvalidPipelineError(msg)
        elif is_async_callable(cleanup):
            msg = "async resource cleanup requires async execution"
            raise InvalidPipelineError(msg)
        elif async_owned_value:
            msg = "async-native resource teardown requires async execution"
            raise InvalidPipelineError(msg)

    def _call_factory[R](self, plan: _ResourcePlan[R]) -> R:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")
        else:
            raw = factory(*plan.args, **plan.kwargs)
            value = self.run_async(raw) if isawaitable(raw) else cast("R", raw)

            if cleanup := plan.cleanup:
                self.callback(cleanup, value)

        return value

    def _enter_lifecycle[R](self, plan: _ResourcePlan[R]) -> R:
        cm = cast("AbstractContextManager[R]", plan.context_manager)
        return self.enter_context(cm)

    def _open[R](self, plan: _ResourcePlan[R]) -> R | MissingType:
        self._validate_sync_teardown(plan)

        if plan.strategy is _ResourceStrategy.EXTERNAL:
            value = plan.value
        elif plan.strategy is _ResourceStrategy.OWNED:
            value = plan.value
            self.callback(close_resource, plan.cleanup, value)
        elif plan.strategy is _ResourceStrategy.VALUE_FACTORY:
            value = self._call_factory(plan)
        else:
            value = self._enter_lifecycle(plan)

        return value

    def _acquire_entry[R](self, resource: Resource[R]) -> Acquisition:
        plan = build_resource_plan(resource)

        try:
            value = self._open(plan)
        except Exception as error:  # noqa: BLE001
            entry: Acquisition = _FailedAcquisition(error)
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

        if resource in self._acquired:
            entry = self._acquired[resource]
        else:
            entry = self._acquire_entry(resource)
            self._acquired[resource] = entry

        if isinstance(entry, _FailedAcquisition):
            raise entry.error

        return cast("R", entry.value)

    def _async_drain(self, source: AsyncIterable[T]) -> Iterator[T]:
        """Pulls an async stream item by item through the execution portal."""
        return async_drain(source, self.run_async)

    def _resolve_inputs(
        self,
        incoming: tuple[GraphEdge, ...],
        steps: SyncExecSteps,
        seed: Iterable[T] | None = None,
    ) -> tuple[Iterator[T], ExtraOutput]:
        source: Iterator[T] | None = None if seed is None else iter(seed)
        indexed: list[tuple[int, Iterator[T]]] = []
        extra: ExtraOutput = {}

        for edge in incoming:
            _require_default_output_port(edge.source_port, f"edge from {edge.source!r}")
            port = parse_port(edge.target_port)
            upstream = steps[edge.source]

            if port.is_default:
                source = upstream
            elif port.index is not None:
                indexed.append((port.index, upstream))
            elif port.name is not None:
                extra[port.name] = upstream

        if indexed:
            ordered = sorted(indexed, key=lambda item: item[0])
            extra["others"] = [stream for _, stream in ordered]

        if source is None:
            seed_items = [] if indexed else cast("list[T]", DEFAULT_SEED)
            source = iter(seed_items)

        return source, extra

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        pairs = self._require_bindings(binding).items()
        return ResourceView({slot: self.acquire(resource) for slot, resource in pairs})

    def _map_stream(
        self, call: Callable[[T], Iterable[T]], source: Iterator[T]
    ) -> Iterator[T]:
        """Maps a bound pipe over its items once the consumer first pulls."""
        func = partial(run_item, call)
        yield from self._pool.map_items(func, source, ordered=self.settings.ordered)

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
        implementation runs its items across the run's worker pool. Concurrency
        applies to synchronous pipes here; iterate asynchronously for concurrent
        async work.

        Args:

            plan: The prepared workflow being run.
            node_id: The node to build.
            steps: The streams already built for upstream nodes.
            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy output stream.

        """
        node = plan.nodes[node_id]
        pipe = node.module.select_sync()
        host_isasync = node.module.is_async_pipe(pipe)
        incoming = plan.index.incoming.get(node_id, ())
        source, extra = self._resolve_inputs(incoming, steps, seed)

        if node.resources:
            extra["resources"] = self._bind_resources(node.resources)

        if node.embed is not None:
            extra["embed"] = select_embed(
                node.embed,
                host_isasync=host_isasync,
                run_sync=_asyncify_call,
                drain=self._async_drain,
            )

        extra.update(cast("Mapping[str, ModuleOptionValues]", node.options))
        conf = node.embed_or_self_conf
        mapped = self._policy.workers is not None and is_mappable(node, extra)

        if node.module.is_async_pipe(pipe):
            _stream = pipe(source, conf=conf, context=self.context, **extra)
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = self._async_drain(require_async_stream(value, pipe))
        elif mapped:
            call = partial(pipe, conf=conf, context=self.context, **extra)
            stream = self._map_stream(cast("Callable[[T], Iterable[T]]", call), source)
        else:
            _stream = pipe(source, conf=conf, context=self.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", _stream)
            stream = require_stream(value, pipe)

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

    def _run_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> Iterator[T]:
        """Builds the item stream for one of the plan's workflow outputs."""
        endpoint, required = _require_output(plan, output)
        steps: SyncExecSteps = {}

        if self._policy.executor is Executor.PROCESS:
            require_process_safe(plan, required, self.context)

        seed = None if source is None else self._build_source_stream(source)
        seed_target = None if seed is None else _require_seed_target(plan, required)

        for node_id in plan.index.order:
            if node_id in required:
                _seed = seed if node_id == seed_target else None
                steps[node_id] = self._build_stream(plan, node_id, steps, _seed)

        return steps[endpoint.node]


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
            stream = aiter(
                await self._abuild_source_stream(_require_source(source, output))
            )
        else:
            stream = await self._arun_plan(plan, output, source)

        return stream

    async def _arun_plan(
        self,
        plan: ExecutionPlan,
        output: str,
        source: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
    ) -> AsyncIterator[T]:
        """Builds the async item stream for one of the plan's workflow outputs."""
        policy = self._policy

        endpoint, required = _require_output(plan, output)
        steps: AsyncExecSteps = {}
        self._reserve_node_threads(plan, required)
        seed = None if source is None else await self._abuild_source_stream(source)
        seed_target = None if seed is None else _require_seed_target(plan, required)

        for node_id in plan.index.order:
            if node_id in required:
                _seed = seed if node_id == seed_target else None
                args = (plan, node_id, steps, _seed, policy)
                steps[node_id] = await self._abuild_stream(*args)

        return steps[endpoint.node]

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

    def _async_resolve_inputs(
        self,
        incoming: tuple[GraphEdge, ...],
        steps: AsyncExecSteps,
        seed: AnyIterable[T] | None = None,
    ) -> tuple[AsyncIterable[T], ExtraOutput]:
        source: AsyncIterable[T] | None = None if seed is None else as_async(seed)
        indexed: list[tuple[int, AsyncIterator[T]]] = []
        extra: ExtraOutput = {}

        for edge in incoming:
            _require_default_output_port(edge.source_port, f"edge from {edge.source!r}")
            port = parse_port(edge.target_port)
            upstream = steps[edge.source]

            if port.is_default:
                source = upstream
            elif port.index is not None:
                indexed.append((port.index, upstream))
            elif port.name is not None:
                extra[port.name] = upstream

        if indexed:
            ordered = sorted(indexed, key=lambda item: item[0])
            extra["others"] = [stream for _, stream in ordered]

        if source is None:
            seed_items = [] if indexed else cast("list[T]", DEFAULT_SEED)
            source = as_async(seed_items)

        return source, extra

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
        conf = node.embed_or_self_conf

        if node.module.is_async_pipe(pipe):

            async def call_native(item: T) -> Iterable[T]:
                raw = pipe(item, conf=conf, context=self.context, **extra)
                value = await as_awaitable(raw)

                if isinstance(value, AsyncIterable):
                    stream = cast("AsyncIterable[T]", value)
                    results: Iterable[T] = [x async for x in stream]
                else:
                    results = cast("Iterator[T]", value)

                return results

            call = call_native
        else:
            kwargs = _bridge_inputs(extra)
            bound = partial(pipe, conf=conf, context=self.context, **kwargs)
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
        conf = node.embed_or_self_conf

        def start() -> tuple[object, Iterator[T]]:
            raw = pipe(worker_source, conf=conf, context=self.context, **bridged)
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

        incoming = plan.index.incoming.get(node_id, ())
        source, extra = self._async_resolve_inputs(incoming, steps, seed)

        if node.resources:
            extra["resources"] = await self._abind_resources(node.resources)

        if node.embed is not None:
            extra["embed"] = select_embed(
                node.embed,
                host_isasync=host_isasync,
                run_sync=self.run_sync,
                drain=partial(async_drain, call=run_from_thread),
            )

        extra.update(cast("Mapping[str, ModuleOptionValues]", node.options))
        limit = policy.limit

        if limit is not None and is_mappable(node, extra):
            call = self._build_item_call(pipe, node, extra, policy)
            stream = self._amap_stream(call, source, limit)
        elif not node.module.is_async_pipe(pipe):
            stream = await self._run_sync_node(pipe, node, source, extra)
        else:
            conf = node.embed_or_self_conf
            _stream = pipe(source, conf=conf, context=self.context, **extra)
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = require_async_stream(value, pipe)

        return stream

    async def aclose(self) -> None:
        """
        Unwinds the exit stack behind a cancellation shield.

        Only the first call shuts the execution down. A repeated call does nothing.
        """
        await self._shutdown()


__all__ = ["AsyncExecution", "SyncExecution"]
