# vim: sw=4:ts=4:expandtab
"""
Private sync/async executions that run a pipeline definition.

A pipeline definition is a reusable structural snapshot; running it creates one
of these one-shot executions. Each owns the task group, exit stack, and sync/async
bridge that bound a run's spawned tasks and acquired resources. These types are
private to the runtime and belong to no supported surface.
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
from riko.bado._util import as_awaitable
from riko.bado.itertools import as_async
from riko.base.exceptions import InvalidPipelineError, PipelineStateError
from riko.definitions._resources import ResourceView
from riko.types._compiler import ModuleOptionValues
from riko.types._guards import is_async_callable, is_async_closeable, is_sync_closeable
from riko.types._workflow import parse_port
from riko.types._wrappers import AsyncModuleWrapperOutput, CoroutineFunc, ModuleWrapper

from ._adapt import (
    adapt_embed_for_async,
    adapt_embed_for_sync,
    drain_async,
    normalize_items,
    pull_stream,
    require_async_stream,
    require_stream,
)
from ._events import _NULL_EVENT_SINK, EventSink
from ._plan import _ResourcePlan, _ResourceStrategy, build_resource_plan
from ._prepared import ExecMode, PreparedNode

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from types import TracebackType

    from anyio.abc import TaskGroup
    from anyio.from_thread import BlockingPortal

    from riko.runtime._execution_plan import ExecutionPlan
    from riko.types._compiler import GraphEdge
    from riko.types._sentinels import MissingType
    from riko.types._wrappers import AsyncModuleWrapper, AysncFunc, SyncModuleWrapper

    from ._resources import Resource
    from .context import Context

type SyncExecSteps[T] = dict[str, Iterator[T]]
type AsyncExecSteps[T] = dict[str, AsyncIterator[T]]
type ExtraObjects[T] = ResourceView | ModuleWrapper | ModuleOptionValues
type ExtraStreams[T] = (
    AsyncIterable[T] | list[AsyncIterable[T]] | Iterator[T] | Iterable[Iterator[T]]
)
type ExtraValues[T] = ExtraObjects[T] | ExtraStreams[T]
type ExtraInput[T] = Mapping[str, ExtraValues[T]]
type ExtraOutput[T] = dict[str, ExtraValues[T]]
type Resolution = _Acquired | _FailedAcquisition
type Resolved = dict[Resource[Any], Resolution]


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
    Re-exposes a worker-run node's async inputs as lazy synchronous streams.

    Args:

        extra: The secondary inputs wired for the node, mixed with the non-stream
            values a node may also receive.

    Returns:

        The same mapping with every async stream replaced by a lazy synchronous
        stream over it, and every other value left as it is.

    """
    bridged: dict[str, ExtraObjects | Iterator[T] | Iterable[Iterator[T]]] = {}

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
class _WorkerContext[T]:
    """Runs a blocking sync context manager's entry and exit on a worker thread."""

    _run: AysncFunc[T]
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


@define(eq=False)
class _BaseExecution:
    """Shares the definition reference and closed-state guard across executions."""

    context: Context | None = None
    events: EventSink = field(default=_NULL_EVENT_SINK, kw_only=True)
    _closing: bool = field(default=False, init=False)
    _cleanup_errors: list[Exception] = field(factory=list, init=False)

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

    def _record_cleanup_error(self, func: Callable, *args: object) -> None:
        """Runs a cleanup callback and saves its failure for the shutdown report."""
        try:
            func(*args)
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

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
class SyncExecution[T](_BaseExecution):
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

    def close(
        self,
        exc_type: type[BaseException] | None = None,
        exc: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> bool:
        """Unwinds the exit stack and stops the portal under the primary error."""
        self._closing = True
        raised: BaseException | None = None
        suppressed = False

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

    @overload
    def enter_context(  # noqa: E704
        self, cm: AbstractContextManager[BlockingPortal]
    ) -> BlockingPortal: ...
    @overload
    def enter_context(self, cm: AbstractContextManager[T]) -> T: ...  # noqa: E704
    def enter_context(  # noqa: E301
        self, cm: AbstractContextManager[BlockingPortal | T]
    ) -> BlockingPortal | T:
        """
        Enters ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

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
    def run_async(
        self, func: Awaitable[T | Iterable[T] | AsyncIterable[T]], /
    ) -> T | Iterable[T] | AsyncIterable[T]: ...  # noqa: E704
    @overload  # noqa: E301
    def run_async(  # noqa: E704
        self,
        func: Callable[..., Awaitable[T | Iterable[T] | AsyncIterable[T]]],
        /,
        *args: object,
    ) -> T | Iterable[T] | AsyncIterable[T]: ...
    def run_async(  # noqa: E301
        self,
        func: Awaitable[T | Iterable[T] | AsyncIterable[T]]
        | Callable[..., Awaitable[T | Iterable[T] | AsyncIterable[T]]],
        *args: object,
    ) -> T | Iterable[T] | AsyncIterable[T]:
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

    def spawn(self, func: AysncFunc[T], *args: object) -> None:
        """
        Schedules a background async task on the execution portal.

        Args:

            func: An async callable to run under the portal task group.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("spawn a task in")
        self.portal.start_task_soon(func, *args)

    def _reject_async_teardown(self, plan: _ResourcePlan[T]) -> None:
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

    def _call_factory(self, plan: _ResourcePlan[T]) -> T | object:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")
        else:
            raw = factory(*plan.args, **plan.kwargs)
            value = self.run_async(raw) if isawaitable(raw) else raw

            if cleanup := plan.cleanup:
                self.callback(cleanup, value)

        return value

    def _enter_lifecycle(self, plan: _ResourcePlan[T]) -> T:
        cm = cast("AbstractContextManager[T]", plan.context_manager)
        return self.enter_context(cm)

    def _open(self, plan: _ResourcePlan[T]) -> T | MissingType | object:
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

    def _resolve(self, resource: Resource[T]) -> Resolution:
        plan = build_resource_plan(resource)

        try:
            value = self._open(plan)
        except Exception as error:  # noqa: BLE001
            entry: Resolution = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    def acquire(self, resource: Resource[T]) -> T:
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

    def _drain_async(self, source: AsyncIterable[T]) -> Iterator[T]:
        """Pulls an async stream item by item through the execution portal."""
        return drain_async(source, self.run_async)

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

    def _default_seed(self) -> Iterator[T]:
        """Produces the seed fed to a node with no default or positional input."""
        return iter([cast("T", {"forever": True})])

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
            source = iter(()) if indexed else self._default_seed()

        return source, extra

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            raise InvalidPipelineError(f"resource(s) {names} not provided to execution")

        values = {slot: self.acquire(available[name]) for slot, name in binding.items()}
        return ResourceView(values)

    def _build_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: SyncExecSteps,
        seed: Iterable[T] | None = None,
    ) -> Iterator[T]:
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
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = self._drain_async(require_async_stream(value, async_pipe))
        else:
            pipe = cast("SyncModuleWrapper", _pipe)
            _stream = pipe(source, conf=conf, context=self.context, **extra)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", _stream)
            stream = require_stream(value, pipe)

        return stream

    def _resolve_source(
        self,
        value: T
        | Iterable[T]
        | AsyncIterable[T]
        | Awaitable[T | Iterable[T] | AsyncIterable[T]],
    ) -> Iterator[T]:
        """Resolves a seed of any accepted shape to one lazy item stream."""
        resolved = self.run_async(value) if isawaitable(value) else value

        if isinstance(resolved, AsyncIterable):
            stream = self._drain_async(resolved)
        else:
            stream = iter(normalize_items(resolved))

        return stream

    def run(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        source: T
        | Iterable[T]
        | AsyncIterable[T]
        | Awaitable[T | Iterable[T] | AsyncIterable[T]]
        | None = None,
    ) -> Iterator[T]:
        """
        Builds the item stream for one of the plan's named outputs.

        Only the selected output's dependency subgraph runs. The returned stream is
        lazy; consume it within this execution's context so its teardown stays owned.

        Args:

            plan: The prepared workflow to run.
            output: The named output to produce.
            source: A seed for the output's open input in place of the default
                empty seed: one item, an item stream, an async item stream, or an
                awaitable resolving to one of those. When omitted, only a node
                with no default or positional input receives that default.

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
        seed = None if source is None else self._resolve_source(source)
        seed_target = None if seed is None else _seed_target(plan, required)

        for node_id in plan.index.order:
            if node_id in required:
                _seed = seed if node_id == seed_target else None
                steps[node_id] = self._build_stream(plan, node_id, steps, _seed)

        return steps[endpoint.node]


@define(eq=False)
class AsyncExecution[T](_BaseExecution):
    """
    Runs a pipeline definition asynchronously behind one owned exit stack.

    Blocking sync components run on a worker thread through the bridge.
    """

    shutdown_timeout: float | None = field(default=None, kw_only=True)
    _stack: AsyncExitStack = field(factory=AsyncExitStack, init=False)
    _task_group: TaskGroup | None = field(default=None, init=False)
    _resolved: Resolved = field(factory=dict, init=False)
    _inflight: dict[Resource[Any], Event] = field(factory=dict, init=False)

    async def __aenter__(self) -> Self:
        self._task_group = create_task_group()
        await self._task_group.__aenter__()
        return self

    async def _join_tasks(self, *, cancel: bool) -> None:
        if self._task_group is not None:
            if cancel:
                self._task_group.cancel_scope.cancel()

            try:
                await self._task_group.__aexit__(None, None, None)
            except Exception as error:  # noqa: BLE001
                self._cleanup_errors.append(error)
            finally:
                self._task_group = None

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
        self._closing = True
        raised: BaseException | None = None
        suppressed = False

        try:
            await self._join_tasks(cancel=exc_type is not None)
        finally:
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

    @overload
    def enter_context(  # noqa: E704
        self, cm: AbstractContextManager[BlockingPortal]
    ) -> BlockingPortal: ...
    @overload
    def enter_context(self, cm: AbstractContextManager[T]) -> T: ...  # noqa: E704
    def enter_context(  # noqa: E301
        self, cm: AbstractContextManager[BlockingPortal | T]
    ) -> BlockingPortal | T:
        """
        Enters a synchronous ``cm`` on the execution exit stack.

        Args:

            cm: A synchronous context manager to own for the execution.

        Returns:

            The value ``cm`` yields on entry.

        """
        self._require_open("add a resource to")
        return self._stack.enter_context(cm)

    async def enter_async_context(self, cm: AbstractAsyncContextManager[T]) -> T:
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

    async def _arecord_cleanup_error(self, func: AysncFunc[T], *args: object) -> None:
        """Awaits a cleanup callback and saves its failure for the shutdown report."""
        try:
            await func(*args)
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

    def push_async_callback(self, func: AysncFunc[T], *args: object) -> None:
        """
        Registers an async ``func`` to run during exit-stack unwind.

        Args:

            func: An async cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add an async callback to")
        self._stack.push_async_callback(self._arecord_cleanup_error, func, *args)

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

    async def _arun_sync[R](self, func: Callable[..., R], *args: object) -> R:
        """
        Runs a blocking sync callable on a worker thread without the open guard.

        Resource teardown runs while the execution is closing, when the guarded
        ``run_sync`` would refuse work, so lifecycle adaptation offloads through here.
        """
        return await asyncify(func)(*args)

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
        return await self._arun_sync(func, *args)

    async def aacquire(self, resource: Resource[T]) -> T:
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

    def _register_teardown(
        self, teardown: Callable, value: object, *, is_async: bool
    ) -> None:
        """Registers ``teardown(value)`` on unwind: on the loop, or a worker if sync."""
        if is_async:
            self.push_async_callback(cast("AysncFunc[T]", teardown), value)
        else:
            self.push_async_callback(self._arun_sync, teardown, value)

    async def _acall_factory(self, plan: _ResourcePlan[T]) -> object:
        if (factory := plan.factory) is None:
            raise InvalidPipelineError("resource factory is required")

        if is_async_callable(factory):
            value: T = await factory(*plan.args, **plan.kwargs)
        else:
            func = cast("Callable[..., T]", partial(factory, *plan.args, **plan.kwargs))
            value = await self._arun_sync(func)

        if (cleanup := plan.cleanup) not in (None, False):
            self._register_teardown(cleanup, value, is_async=is_async_callable(cleanup))

        return value

    async def _aenter_lifecycle(self, plan: _ResourcePlan[T]) -> object:
        if plan.native_async:
            cm = cast("AbstractAsyncContextManager[T]", plan.context_manager)
        else:
            _cm = cast("AbstractContextManager[T]", plan.context_manager)
            cm = _WorkerContext(self._arun_sync, _cm)

        return await self.enter_async_context(cm)

    async def _aopen(self, plan: _ResourcePlan[T]) -> object:
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

    async def _aresolve(self, resource: Resource[T]) -> Resolution:
        plan = build_resource_plan(resource)

        try:
            value = await self._aopen(plan)
        except Exception as error:  # noqa: BLE001
            entry: Resolution = _FailedAcquisition(error)
        else:
            entry = _Acquired(value)

        return entry

    async def _aresolve_once(self, resource: Resource[T]) -> Resolution:
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

    async def run(
        self,
        plan: ExecutionPlan,
        output: str = "default",
        *,
        source: T
        | Iterable[T]
        | AsyncIterable[T]
        | Awaitable[T | Iterable[T] | AsyncIterable[T]]
        | None = None,
    ) -> AsyncIterator[T]:
        """
        Builds the async item stream for one of the plan's named outputs.

        Only the selected output's dependency subgraph runs. The returned stream is
        lazy; consume it within this execution's context so its teardown stays owned.

        Args:

            plan: The prepared workflow to run.
            output: The named output to produce.
            source: A seed for the output's open input in place of the default
                empty seed: one item, an item stream, an async item stream, or an
                awaitable resolving to one of those. When omitted, only a node
                with no default or positional input receives that default.

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
        seed = None if source is None else await self._aresolve_source(source)
        seed_target = None if seed is None else _seed_target(plan, required)

        for node_id in plan.index.order:
            if node_id in required:
                _seed = seed if node_id == seed_target else None
                args = (plan, node_id, steps, _seed)
                steps[node_id] = await self._abuild_stream(*args)

        return steps[endpoint.node]

    async def _aresolve_source(
        self,
        value: T
        | Iterable[T]
        | AsyncIterable[T]
        | Awaitable[T | Iterable[T] | AsyncIterable[T]],
    ) -> AsyncIterable[T]:
        """Resolves a seed of any accepted shape to one lazy async item stream."""
        resolved = await as_awaitable(value)

        if isinstance(resolved, AsyncIterable):
            stream: AsyncIterable[T] = resolved
        else:
            stream = as_async(normalize_items(resolved))

        return stream

    def _adefault_seed(self) -> AsyncIterable[T]:
        """Produces the seed fed to a node with no default or positional input."""
        seed: list[T] = [cast("T", {"forever": True})]
        return as_async(seed)

    def _aresolve_inputs(
        self,
        incoming: tuple[GraphEdge, ...],
        steps: AsyncExecSteps,
        seed: Iterable[T] | AsyncIterable[T] | None = None,
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
            items: list[T] = []
            source = as_async(items) if indexed else self._adefault_seed()

        return source, extra

    async def _abind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            raise InvalidPipelineError(f"resource(s) {names} not provided to execution")

        items = binding.items()
        values = {slot: await self.aacquire(available[name]) for slot, name in items}
        return ResourceView(values)

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

    async def _run_sync_node(
        self,
        pipe: SyncModuleWrapper,
        node: PreparedNode,
        source: AsyncIterable[T],
        extra: ExtraInput,
    ) -> AsyncIterator[T]:
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

        def start() -> tuple[object, Iterator[T]]:
            raw = pipe(worker_source, conf=conf, context=self.context, **bridged)
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            return raw, require_stream(value, pipe)

        raw, iterator = await self.run_sync(start)
        return pull_stream(iterator, raw, self.run_sync, self._arun_sync)

    async def _abuild_stream(
        self,
        plan: ExecutionPlan,
        node_id: str,
        steps: AsyncExecSteps,
        seed: Iterable[T] | AsyncIterable[T] | None = None,
    ) -> AsyncIterator[T]:
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
            value = cast("AsyncModuleWrapperOutput[T]", _stream)
            stream = require_async_stream(value, async_pipe)

        return stream

    async def aclose(self) -> None:
        """Joins the task group, then unwinds the exit stack behind a shield."""
        await self._shutdown()


__all__ = ["AsyncExecution", "SyncExecution"]
