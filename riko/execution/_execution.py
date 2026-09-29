# vim: sw=4:ts=4:expandtab
"""
Private sync/async executions that run a pipeline definition.

A pipeline definition is a reusable structural snapshot; running it creates one
of these one-shot executions. Each owns the task group, exit stack, and sync/async
bridge that bound a run's spawned tasks and acquired resources. These types are
private to the runtime and belong to no supported surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Mapping
from contextlib import AsyncExitStack, ExitStack, nullcontext
from functools import cached_property, partial
from inspect import isawaitable
from itertools import chain
from typing import TYPE_CHECKING, Any, Self, cast, overload

from attrs import define, field

from riko.bado._backend import (
    CancelScope,
    Event,
    asyncify,
    create_task_group,
    fail_after,
    run_from_thread,
    start_blocking_portal,
)
from riko.bado.itertools import as_async
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.definitions._resources import ResourceView
from riko.types._compiler import ModuleOptionValues
from riko.types._guards import is_async_callable, is_async_closeable, is_sync_closeable
from riko.types._workflow import parse_port
from riko.types._wrappers import CoroutineFunc, ModuleWrapper

from ._adapt import (
    adapt_embed_for_async,
    adapt_embed_for_sync,
    drain_async,
    pull_stream,
    require_async_stream,
    require_stream,
)
from ._events import _NULL_EVENT_SINK, EventSink
from ._plan import _ResourcePlan, _ResourceStrategy, build_resource_plan
from ._prepared import ExecMode, PreparedNode

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio.abc import TaskGroup
    from anyio.from_thread import BlockingPortal

    from riko.runtime._execution_plan import ExecutionPlan
    from riko.types._compiler import GraphEdge
    from riko.types._sentinels import MissingType
    from riko.types._streams import (
        AsyncItems,
        AsyncStream,
        Item,
        Items,
        Stream,
        Streams,
    )
    from riko.types._wrappers import (
        AsyncModuleWrapper,
        AysncFunc,
        Func,
        SyncModuleWrapper,
    )

    from ._resources import Resource
    from .context import Context

type SyncExecSteps = dict[str, Stream]
type AsyncExecSteps = dict[str, AsyncStream]
type ExtraObjects = ResourceView | ModuleWrapper | ModuleOptionValues
type ExtraStreams = AsyncItems | list[AsyncItems] | Stream | Streams
type ExtraValues = ExtraObjects | ExtraStreams
type ExtraInput = Mapping[str, ExtraValues]
type ExtraOutput = dict[str, ExtraValues]
type Resolution = _Acquired | _FailedAcquisition
type Resolved = dict[Resource[Any], Resolution]


@overload
def _bridge_inputs(  # noqa: E704
    extra: Mapping[str, AsyncItems | Stream],
) -> Mapping[str, Stream]: ...
@overload  # noqa: E302
def _bridge_inputs(  # noqa: E704
    extra: Mapping[str, ExtraObjects],
) -> Mapping[str, ExtraObjects]: ...
@overload  # noqa: E302
def _bridge_inputs(  # noqa: E704
    extra: Mapping[str, list[AsyncItems] | Streams],
) -> Mapping[str, Streams]: ...
@overload  # noqa: E302
def _bridge_inputs(  # noqa: E704
    extra: ExtraInput,
) -> Mapping[str, ExtraObjects | Stream | Streams]: ...
def _bridge_inputs(  # noqa: E302
    extra: ExtraInput,
) -> Mapping[str, ExtraObjects | Stream | Streams]:
    """
    Re-exposes a worker-run node's async inputs as lazy synchronous streams.

    Args:

        extra: The secondary inputs wired for the node, mixed with the non-stream
            values a node may also receive.

    Returns:

        The same mapping with every async stream replaced by a lazy synchronous
        stream over it, and every other value left as it is.

    """
    bridged: dict[str, ExtraObjects | Stream | Streams] = {}

    for key, value in extra.items():
        if isinstance(value, AsyncIterable):
            bridged[key] = drain_async(value, run_from_thread)
        elif isinstance(value, list):
            _bridged = (_bridge_inputs({key: v}).values() for v in value)
            bridged[key] = list(chain.from_iterable(_bridged))
        else:
            bridged[key] = value

    return bridged


async def _asyncify_call[T](func: Callable[..., T], *args: object) -> T:
    """
    Runs a blocking callable on a worker thread from the current event loop.

    Args:

        func: The blocking callable to offload.
        args: Positional arguments forwarded to ``func``.

    Returns:

        The value ``func`` returns.

    """
    return await asyncify(func)(*args)


def _seed_target(plan: ExecutionPlan, required: frozenset[str]) -> str:
    """
    Supplies the one node in ``required`` whose default input is open to a seed.

    A node's default input is open when no incoming stream edge targets its bare
    default input port. A piped source needs exactly one such node.

    Args:

        plan: The prepared workflow being run.
        required: The node ids that the selected output's subgraph runs.

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
        msg = f"a piped source requires exactly one open input, found {count}"
        raise InvalidPipelineError(msg)

    return target


def _require_default_output_port(port: str, ref: str) -> None:
    """
    Rejects a non-default output port until multi-output delivery is executable.

    Only the bare ``out`` port is executable today; a positional ``out:N`` or
    semantic ``out:<name>`` source or selected output is refused rather than
    silently read as the node's default ``out`` stream.

    Args:

        port: The source or selected-output port string to check.
        ref: A human-readable reference to the offending edge or output.

    Raises:

        InvalidPipelineError: If ``port`` is not the default ``out`` port.

    """
    if not parse_port(port).is_default:
        msg = f"{ref} uses un-supported non-default output {port=}."
        raise InvalidPipelineError(msg)


@define(frozen=True, slots=True)
class _Acquired:
    """Holds a successfully acquired resource value for single-flight replay."""

    value: object


@define(frozen=True, slots=True)
class _FailedAcquisition:
    """Holds a failed acquisition so repeated use replays the same error."""

    error: BaseException


def _owned_teardown_is_async[T](resource: Resource[T], value: object) -> bool:
    """An owned value tears down asynchronously via an async cleanup or ``aclose``."""
    if resource.cleanup is None:
        native_async = (
            not resource.external
            and is_async_closeable(value)
            and not is_sync_closeable(value)
        )
    else:
        native_async = is_async_callable(resource.cleanup)

    return native_async


@define(eq=False)
class _WorkerContext:
    """Runs a blocking sync context manager's entry and exit on a worker thread."""

    _run: AysncFunc
    _cm: AbstractContextManager[object]

    async def __aenter__(self) -> object:
        return await self._run(self._cm.__enter__)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return bool(await self._run(self._cm.__exit__, exc_type, exc, traceback))


@define(eq=False)
class _BaseExecution:
    """Shares the definition reference and closed-state guard across executions."""

    context: Context | None = None
    events: EventSink = field(default=_NULL_EVENT_SINK, kw_only=True)
    _closing: bool = field(default=False, init=False)

    def emit(self, event: object) -> None:
        """
        Dispatches ``event`` to the execution event sink.

        Args:

            event: The event value produced during a run.

        """
        self.events.emit(event)

    @property
    def closing(self) -> bool:
        return self._closing

    def _require_open(self, action: str) -> None:
        if self._closing:
            raise PipelineStateError("closing", action)

    def _report_shutdown(
        self, exc_type: type[BaseException] | None, errors: list[Exception]
    ) -> None:
        if not errors:
            pass
        elif exc_type is None and len(errors) == 1:
            raise errors[0]
        else:
            raise ExceptionGroup("Execution shutdown failed", errors)


@define(eq=False)
class SyncExecution(_BaseExecution):
    """
    Runs a pipeline definition synchronously behind one owned exit stack.

    Async-only components run through a lazily started blocking portal.

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
    _resolved: Resolved = field(factory=dict, init=False)

    def __enter__(self) -> Self:
        return self

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

    def enter_context[T](self, cm: AbstractContextManager[T]) -> T:
        """
        Enters ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

    def callback(self, func: Func, *args: object) -> None:
        """
        Registers ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(func, *args)

    @overload
    def run_async[T](self, func: Awaitable[T], /) -> T: ...  # noqa: E704
    @overload  # noqa: E301
    def run_async[T](  # noqa: E704
        self, func: Callable[..., Awaitable[T]], /, *args: object
    ) -> T: ...
    def run_async[T](  # noqa: E301
        self, func: Awaitable[T] | Callable[..., Awaitable[T]], *args: object
    ) -> T:
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

    def spawn(self, func: AysncFunc, *args: object) -> None:
        """
        Schedules a background async task on the execution portal.

        Args:

            func: An async callable to run under the portal task group.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("spawn a task in")
        self.portal.start_task_soon(func, *args)

    def acquire[T](self, resource: Resource[T]) -> T:
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

        if resource in self._resolved:
            entry = self._resolved[resource]
        else:
            entry = self._resolve(resource)
            self._resolved[resource] = entry

        if isinstance(entry, _FailedAcquisition):
            raise entry.error

        return cast("T", entry.value)

    def _resolve[T](self, resource: Resource[T]) -> Resolution:
        plan = build_resource_plan(resource)

        try:
            value = self._open(plan)
        except Exception as error:  # noqa: BLE001
            entry: Resolution = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    def _open[T](self, plan: _ResourcePlan[T]) -> T | MissingType | object:
        self._reject_async_teardown(plan)

        if plan.strategy is _ResourceStrategy.EXTERNAL:
            value: object = plan.value
        elif plan.strategy is _ResourceStrategy.OWNED:
            value = plan.value
            self.callback(plan.resource.close, value)
        elif plan.strategy is _ResourceStrategy.VALUE_FACTORY:
            value = self._call_factory(plan)
        else:
            value = self._enter_lifecycle(plan)

        return value

    def _reject_async_teardown[T](self, plan: _ResourcePlan[T]) -> None:
        resource = plan.resource
        is_lifecycle = plan.strategy is _ResourceStrategy.LIFECYCLE
        is_value_factory = plan.strategy is _ResourceStrategy.VALUE_FACTORY
        native_lifecycle = is_lifecycle and plan.native_async
        cleanup = plan.cleanup if is_value_factory else resource.cleanup

        async_owned_value = (
            plan.strategy is _ResourceStrategy.OWNED
            and not resource.external
            and resource.cleanup is None
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

    def _call_factory[T](self, plan: _ResourcePlan[T]) -> T | object:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")
        else:
            raw = factory(*plan.args, **plan.kwargs)
            value = self.run_async(raw) if isawaitable(raw) else raw

            if cleanup := plan.cleanup:
                self.callback(cleanup, value)

        return value

    def _enter_lifecycle[T](self, plan: _ResourcePlan[T]) -> T:
        cm = cast("AbstractContextManager[T]", plan.context_manager)
        return self.enter_context(cm)

    def _select_embed(self, embed: PreparedNode, *, host_async: bool) -> ModuleWrapper:
        """
        Chooses a loop embed's callable in the mode its host pipe actually runs in.

        Args:

            embed: The embed node resolved alongside the loop node.
            host_async: Whether the loop pipe itself runs asynchronously.

        Returns:

            The embed's native callable for that mode, or a host-mode wrapper
            around its other-mode callable.

        """
        pipe, mode = embed.select(is_async=host_async)

        if mode is ExecMode.NATIVE:
            result = pipe
        elif host_async:
            sync_pipe = cast("SyncModuleWrapper", pipe)
            result = adapt_embed_for_async(sync_pipe, _asyncify_call)
        else:
            async_pipe = cast("AsyncModuleWrapper", pipe)
            result = adapt_embed_for_sync(async_pipe, self._drain_async)

        return result

    def _build_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: SyncExecSteps,
        seed: Items | None = None,
    ) -> Stream:
        node = plan.nodes[node_id]
        _pipe, mode = node.select(is_async=False)
        host_async = mode is ExecMode.ADAPTER

        incoming = plan.index.incoming.get(node_id, ())
        source, extra = self._resolve_inputs(incoming, steps, seed)

        if node.resources:
            extra["resources"] = self._bind_resources(node.resources)

        if node.embed is not None:
            extra["embed"] = self._select_embed(node.embed, host_async=host_async)

        extra.update(cast("Mapping[str, ModuleOptionValues]", node.options))
        conf = node.embed_or_self_conf

        if mode is ExecMode.ADAPTER:
            async_pipe = cast("AsyncModuleWrapper", _pipe)
            _stream = async_pipe(source, conf=conf, context=self.context, **extra)
            stream = self._drain_async(require_async_stream(_stream, async_pipe))
        else:
            pipe = cast("SyncModuleWrapper", _pipe)
            _stream = pipe(source, conf=conf, context=self.context, **extra)
            stream = require_stream(_stream, pipe)

        return stream

    def run(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        source: Items | None = None,
    ) -> Stream:
        """
        Builds the item stream for one of the plan's named outputs.

        Only the selected output's dependency subgraph runs. The returned stream is
        lazy; consume it within this execution's context so its teardown stays owned.

        Args:

            plan: The prepared workflow to run.
            output: The named output to produce.
            source: Items to seed the output's open input in place of the default
                empty seed. When omitted, only a node with no default or
                positional input receives that default.

        Returns:

            The item stream produced at the selected output.

        Raises:

            InvalidPipelineError: If the plan exposes no such output, or if
                ``source`` is supplied but the output has no single open input.

        """
        self._require_open("run")

        if (endpoint := plan.index.outputs.get(output)) is None:
            raise InvalidPipelineError(f"workflow has no output {output!r}")

        steps: SyncExecSteps = {}
        _require_default_output_port(endpoint.port, f"output {output!r}")
        required = plan.required[output]
        seed_target = None if source is None else _seed_target(plan, required)

        for node_id in plan.index.order:
            if node_id in required:
                _source = source if node_id == seed_target else None
                steps[node_id] = self._build_stream(plan, node_id, steps, _source)

        return steps[endpoint.node]

    def _drain_async(self, source: AsyncItems) -> Stream:
        """Pulls an async stream item by item through the execution portal."""
        return drain_async(source, self.run_async)

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            raise InvalidPipelineError(f"resource(s) {names} not provided to execution")

        values = {slot: self.acquire(available[name]) for slot, name in binding.items()}
        return ResourceView(values)

    def _resolve_inputs(
        self,
        incoming: tuple[GraphEdge, ...],
        steps: SyncExecSteps,
        seed: Items | None = None,
    ) -> tuple[Stream, ExtraOutput]:
        source: Stream | None = None if seed is None else iter(seed)
        indexed: list[tuple[int, Stream]] = []
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
            source = iter(()) if indexed else self._normalize_source()

        return source, extra

    def _normalize_source(self) -> Stream:
        """Produces the seed fed to a node with no default or positional input."""
        return iter([{"forever": True}])

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        """Unwinds the exit stack, stopping the portal, under the primary error."""
        self._closing = True
        errors: list[Exception] = []
        suppressed = False

        try:
            suppressed = bool(self._stack.__exit__(exc_type, exc, traceback))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

        self._report_shutdown(exc_type, errors)
        return suppressed


@define(eq=False)
class AsyncExecution(_BaseExecution):
    """
    Runs a pipeline definition asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge.
    """

    _shutdown_timeout: float | None = field(default=None, kw_only=True)
    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _task_group: TaskGroup | None = field(default=None, init=False)
    _resolved: Resolved = field(factory=dict, init=False)
    _inflight: dict[Resource[Any], Event] = field(factory=dict, init=False)

    async def __aenter__(self) -> Self:
        self._task_group = create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return await self._shutdown(exc_type, exc, traceback)

    def enter_context[T](self, cm: AbstractContextManager[T]) -> T:
        """
        Enters a synchronous ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

    async def enter_async_context[T](self, cm: AbstractAsyncContextManager[T]) -> T:
        """
        Enters an async ``cm`` on the execution exit stack.

        Args:

            cm: An asynchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add an async resource to")
        return await self._stack.enter_async_context(cm)

    def callback(self, func: Func, *args: object) -> None:
        """
        Registers a synchronous ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(func, *args)

    def push_async_callback(self, func: AysncFunc, *args: object) -> None:
        """
        Registers an async ``func`` to run during exit-stack unwind.

        Args:

            func: An async cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add an async callback to")
        self._stack.push_async_callback(func, *args)

    def spawn(self, func: CoroutineFunc, *args: object) -> None:
        """
        Schedules a background task under the root task group.

        Args:

            func: An async callable to run under the execution task group.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("spawn a task in")

        if self._task_group is None:
            raise PipelineStateError("new", "spawn a task in")

        self._task_group.start_soon(func, *args)

    async def run_sync[T](self, func: Callable[..., T], *args: object) -> T:
        """
        Runs a blocking sync callable on a worker thread through the bridge.

        Args:

            func: A synchronous callable to run off the event loop.
            args: Positional arguments forwarded to ``func``.

        Returns:

            The value ``func`` returns.

        """
        self._require_open("run work in")
        return await self._arun_sync(func, *args)

    async def _arun_sync[T](self, func: Callable[..., T], *args: object) -> T:
        """
        Runs a blocking sync callable on a worker thread without the open guard.

        Resource teardown runs while the execution is closing, when the guarded
        ``run_sync`` would refuse work, so lifecycle adaptation offloads through here.
        """
        return await asyncify(func)(*args)

    async def aacquire[T](self, resource: Resource[T]) -> T:
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
        entry = await self._aresolve_once(resource)

        if isinstance(entry, _FailedAcquisition):
            raise entry.error

        return cast("T", entry.value)

    async def _aresolve_once[T](self, resource: Resource[T]) -> Resolution:
        if resource in self._resolved:
            entry = self._resolved[resource]
        elif (event := self._inflight.get(resource)) is not None:
            await event.wait()
            entry = await self._aresolve_once(resource)
        else:
            event = Event()
            self._inflight[resource] = event

            try:
                entry = await self._aresolve(resource)
                self._resolved[resource] = entry
            finally:
                del self._inflight[resource]
                event.set()

        return entry

    async def _aresolve[T](self, resource: Resource[T]) -> Resolution:
        plan = build_resource_plan(resource)

        try:
            value = await self._aopen(plan)
        except Exception as error:  # noqa: BLE001
            entry: Resolution = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    def _register_teardown(
        self, teardown: Func, value: object, *, is_async: bool
    ) -> None:
        """Registers ``teardown(value)`` on unwind: on the loop, or a worker if sync."""
        if is_async:
            self.push_async_callback(cast("AysncFunc", teardown), value)
        else:
            self.push_async_callback(self._arun_sync, teardown, value)

    async def _aopen[T](self, plan: _ResourcePlan[T]) -> object:
        if plan.strategy is _ResourceStrategy.EXTERNAL:
            value: object = plan.value
        elif plan.strategy is _ResourceStrategy.OWNED:
            value = plan.value
            is_async = _owned_teardown_is_async(plan.resource, value)
            teardown = plan.resource.aclose if is_async else plan.resource.close
            self._register_teardown(teardown, value, is_async=is_async)
        elif plan.strategy is _ResourceStrategy.VALUE_FACTORY:
            value = await self._acall_factory(plan)
        else:
            value = await self._aenter_lifecycle(plan)

        return value

    async def _acall_factory[T](self, plan: _ResourcePlan[T]) -> object:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")

        if is_async_callable(factory):
            value: object = await factory(*plan.args, **plan.kwargs)
        else:
            value = await self._arun_sync(partial(factory, *plan.args, **plan.kwargs))

        if (cleanup := plan.cleanup) not in (None, False):
            self._register_teardown(cleanup, value, is_async=is_async_callable(cleanup))

        return value

    async def _aenter_lifecycle[T](self, plan: _ResourcePlan[T]) -> object:
        if plan.native_async:
            cm = cast("AbstractAsyncContextManager[object]", plan.context_manager)
        else:
            _cm = cast("AbstractContextManager[object]", plan.context_manager)
            cm = _WorkerContext(self._arun_sync, _cm)

        return await self.enter_async_context(cm)

    async def run(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        source: Items | None = None,
    ) -> AsyncStream:
        """
        Builds the async item stream for one of the plan's named outputs.

        Only the selected output's dependency subgraph runs. The returned stream is
        lazy; consume it within this execution's context so its teardown stays owned.

        Args:

            plan: The prepared workflow to run.
            output: The named output to produce.
            source: Items to seed the output's open input in place of the default
                empty seed. When omitted, only a node with no default or
                positional input receives that default.

        Returns:

            The async item stream produced at the selected output.

        Raises:

            InvalidPipelineError: If the plan exposes no such output, or if
                ``source`` is supplied but the output has no single open input.

        """
        self._require_open("run")

        if (endpoint := plan.index.outputs.get(output)) is None:
            raise InvalidPipelineError(f"workflow has no output {output!r}")

        steps: AsyncExecSteps = {}
        _require_default_output_port(endpoint.port, f"output {output!r}")
        required = plan.required[output]
        seed_target = None if source is None else _seed_target(plan, required)

        for node_id in plan.index.order:
            if node_id in required:
                _source = source if node_id == seed_target else None
                args = (plan, node_id, steps, _source)
                steps[node_id] = await self._abuild_stream(*args)

        return steps[endpoint.node]

    async def _run_sync_node(
        self,
        pipe: SyncModuleWrapper,
        node: PreparedNode,
        source: AsyncItems,
        extra: ExtraInput,
    ) -> AsyncStream:
        """
        Streams a sync-only node's output without materializing it.

        The pipe runs on a worker thread, reads its async inputs lazily from
        there, and its output is pulled one item at a time as the consumer asks
        for it.

        Args:

            pipe: The node's synchronous pipe.
            node: The prepared node being run.
            source: The node's primary async input stream.
            extra: The node's secondary inputs and non-stream arguments.

        Returns:

            The async item stream produced by the node.

        """
        bridged = _bridge_inputs(extra)
        worker_source = drain_async(source, run_from_thread)
        conf = node.embed_or_self_conf

        def start() -> tuple[object, Stream]:
            raw = pipe(worker_source, conf=conf, context=self.context, **bridged)
            return raw, require_stream(raw, pipe)

        raw, iterator = await self.run_sync(start)
        return pull_stream(iterator, raw, self.run_sync, self._arun_sync)

    def _select_embed(self, embed: PreparedNode, *, host_async: bool) -> ModuleWrapper:
        """
        Chooses a loop embed's callable in the mode its host pipe actually runs in.

        Args:

            embed: The embed node resolved alongside the loop node.
            host_async: Whether the loop pipe itself runs asynchronously.

        Returns:

            The embed's native callable for that mode, or a host-mode wrapper
            around its other-mode callable.

        """
        pipe, mode = embed.select(is_async=host_async)

        if mode is ExecMode.NATIVE:
            result = pipe
        elif host_async:
            sync_pipe = cast("SyncModuleWrapper", pipe)
            result = adapt_embed_for_async(sync_pipe, self.run_sync)
        else:
            async_pipe = cast("AsyncModuleWrapper", pipe)
            result = adapt_embed_for_sync(
                async_pipe, partial(drain_async, call=run_from_thread)
            )

        return result

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: AsyncExecSteps,
        seed: Items | None = None,
    ) -> AsyncStream:
        node = plan.nodes[node_id]
        _pipe, mode = node.select(is_async=True)
        host_async = mode is ExecMode.NATIVE

        incoming = plan.index.incoming.get(node_id, ())
        source, extra = self._aresolve_inputs(incoming, steps, seed)

        if node.resources:
            extra["resources"] = await self._abind_resources(node.resources)

        if node.embed is not None:
            extra["embed"] = self._select_embed(node.embed, host_async=host_async)

        extra.update(cast("Mapping[str, ModuleOptionValues]", node.options))

        if mode is ExecMode.ADAPTER:
            pipe = cast("SyncModuleWrapper", _pipe)
            stream = await self._run_sync_node(pipe, node, source, extra)
        else:
            conf = node.embed_or_self_conf
            async_pipe = cast("AsyncModuleWrapper", _pipe)
            _stream = async_pipe(source, conf=conf, context=self.context, **extra)
            stream = require_async_stream(_stream, async_pipe)

        return stream

    async def _abind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            raise InvalidPipelineError(f"resource(s) {names} not provided to execution")

        items = binding.items()
        values = {slot: await self.aacquire(available[name]) for slot, name in items}
        return ResourceView(values)

    def _aresolve_inputs(
        self,
        incoming: tuple[GraphEdge, ...],
        steps: AsyncExecSteps,
        seed: Items | None = None,
    ) -> tuple[AsyncItems, ExtraOutput]:
        source: AsyncItems | None = None if seed is None else as_async(seed)
        indexed: list[tuple[int, AsyncStream]] = []
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
            items: Items = []
            source = as_async(items) if indexed else self._anormalize_source()

        return source, extra

    def _anormalize_source(self) -> AsyncItems:
        """Produces the seed fed to a node with no default or positional input."""
        seed: list[Item] = [{"forever": True}]
        return as_async(seed)

    async def aclose(self) -> None:
        """Joins the task group, then unwinds the exit stack behind a shield."""
        await self._shutdown()

    async def _shutdown(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        self._closing = True
        errors: list[Exception] = []
        suppressed = False

        try:
            await self._join_tasks(cancel=exc_type is not None, errors=errors)
        finally:
            suppressed = await self._unwind(exc_type, exc, traceback, errors=errors)

        self._report_shutdown(exc_type, errors)
        return suppressed

    async def _join_tasks(self, *, cancel: bool, errors: list[Exception]) -> None:
        if self._task_group is not None:
            if cancel:
                self._task_group.cancel_scope.cancel()

            try:
                await self._task_group.__aexit__(None, None, None)
            except Exception as error:  # noqa: BLE001
                errors.append(error)
            finally:
                self._task_group = None

    async def _unwind(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        *,
        errors: list[Exception],
    ) -> bool:
        suppressed = False
        missing_timeout = self._shutdown_timeout is None
        bound = nullcontext() if missing_timeout else fail_after(self._shutdown_timeout)

        with CancelScope(shield=True), bound:
            try:
                suppressed = bool(await self._stack.__aexit__(exc_type, exc, traceback))
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        return suppressed


__all__ = ["AsyncExecution", "SyncExecution"]
