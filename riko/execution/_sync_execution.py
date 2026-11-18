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
from inspect import isawaitable, isgenerator
from itertools import islice
from operator import attrgetter
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast, overload

from attrs import define, field

from riko.bado._backend import fail_after, start_blocking_portal
from riko.bado._util import maybe_closing, run_bridged
from riko.base._config import DEFAULT_OUTPUT, settings
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._funcutils import call_if_distinct, map_values
from riko.base._guards import ASYNC_CLEANUP_MSG, is_async_callable, is_awaitable
from riko.base._iterutils import Tee, auto_close
from riko.base._require_guards import require_non_null
from riko.coercion._sequences import listize
from riko.types._enums import Executor
from riko.types._feed import (
    EnvelopeStream,
    ItemCall,
    OutputPorts,
    PortMap,
    TrackedCall,
    _ItemEnvelope,
)
from riko.types._io import resolve_closer
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    OwnedPlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
)
from riko.types._workflow import OUT

from ._adapt import to_sync
from ._concurrency import build_item_call, build_tracked_call, require_process_safe
from ._execution import (
    DEFAULT_ENVELOPES,
    Acquisition,
    SyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._pools import _PoolLifetime
from ._prepared import (
    NO_PIPE_MSG,
    AsyncInterface,
    ExecutionExtras,
    PreparedNode,
    PreparedSplitter,
    SyncInterface,
)
from ._provenance import NodeProvenance, gen_result_envelopes
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import AsyncIterator, Awaitable
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from anyio.from_thread import BlockingPortal

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._enums import IdentityMode
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import AnyIterable, AsyncCascade, Cascade
    from riko.types._workflow import NodeId, OutputName, PortKey
    from riko.types._wrappers import AsyncFunc, Func

    from ._prepared import ExecutionPlan

_get_value = attrgetter("value")
_unwrap = partial(map, _get_value)


def _gen_item_stream[T](
    call: ItemCall[T],
    node_id: NodeId,
    identity: IdentityMode | None,
    stream: EnvelopeStream[T],
) -> EnvelopeStream[T]:
    """
    Runs a mappable node's per-item call on each envelope's value, one item at a time.

    The item being read is closed when the stream is closed early.
    """
    for parent in stream:
        with maybe_closing(call(parent.value)) as results:
            yield from gen_result_envelopes(node_id, results, parent, identity)


def _wrap(
    values: Iterator[object], envelopes: EnvelopeStream[object]
) -> EnvelopeStream[object]:
    """Matches each splitter branch value with the input envelope it came from."""
    for value, envelope in zip(values, envelopes, strict=False):
        yield envelope.with_value(value)


def _maybe_close[T](
    value: T,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    is_async: bool = False,
    bridge: Callable[[Awaitable[object]], object] | None = None,
) -> None:
    """Closes a value now if it has a close."""
    closer = resolve_closer(value, cleanup=cleanup, is_async=is_async)

    if closer is not None:
        run_bridged(closer, bridge)


def _queue_close[T](
    callback: Callable[[Func[None]], object],
    value: T,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    is_async: bool = False,
    bridge: Callable[[Awaitable[object]], object] | None = None,
) -> None:
    """Hands ``callback`` the value's close to run later, if it has one."""
    closer = resolve_closer(value, cleanup=cleanup, is_async=is_async)

    if closer is not None:
        callback(partial(run_bridged, closer, bridge))


@define(eq=False)
class _PortalLifecycle[T]:
    """
    Enters an async lifecycle's context manager for a sync execution.

    The portal runs its entry and exit in one task. The exit is bounded by the shutdown
    timeout, whose expiry is recorded. The async execution has no twin. It bounds its
    whole unwind once instead.
    """

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
class _Owned[T]:
    """
    Wraps an owned iterator so it closes once, however many owners close it.

    The flag is set before the close runs. A failing close is not retried.
    """

    _value: Iterator[T]
    _closed: bool = field(default=False, init=False)

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        return next(self._value)

    def close(self) -> None:
        """Closes the iterator unless it is already closed."""
        if not self._closed:
            self._closed = True
            _maybe_close(self._value)


@define(eq=False)
class _RunStream[T]:
    """
    One run's output stream, which owns every node stream the run built.

    Closing this closes the streams last built first, output first. Only the first close
    does anything.
    """

    context: Context | None
    _steps: list[object] = field(factory=list, init=False)
    _closers: list[Func[None]] = field(factory=list, init=False)
    _closed: bool = field(default=False, init=False)

    @property
    def _output(self) -> Iterator[T]:
        """The endpoint's stream, the step the run added last."""
        if not isinstance(step := self._steps[-1], Iterator):
            msg = "the run's output must be an iterator"
            raise TypeError(msg)

        return step

    def add(self, *values: object) -> None:
        """
        Adds the streams the run built, or the values they were drawn from.

        Raises:

            InvalidPipelineError: Before any item is read, if a value's only close is
                async.

        """
        for value in values:
            self._steps.append(value)
            _queue_close(self._closers.append, value)

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        return next(self._output)

    def close(self) -> None:
        """Closes every node stream, last built first."""
        if not self._closed:
            self._closed = True

            with ExitStack() as stack:
                for closer in self._closers:
                    stack.callback(closer)


@define(eq=False)
class SyncExecution[T](_BaseExecution[ExitStack]):
    """
    Runs a prepared workflow synchronously behind one owned exit stack.

    Async-only components run through a lazily started blocking portal. The
    execution settings decide whether mappable nodes spread their items across
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
    is_async: ClassVar[bool] = False

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

    def _to_sync[R](self, stream: AsyncIterator[R]) -> Iterator[R]:
        """Pulls an async stream item by item through the execution portal."""
        return to_sync(self.run_async, stream)

    def _drain_owned[R](self, stream: AsyncIterator[R]) -> Iterator[R]:
        """Drains an async iterator this execution owns and closes it at exit."""
        self.register_owned(stream, is_async=True)
        return self._to_sync(stream)

    @overload
    def run_async[R](self, value: Awaitable[R], /) -> R: ...
    @overload
    def run_async[R](self, value: AsyncFunc[R], /, *args: object) -> R: ...
    def run_async[R](self, value: Awaitable[R] | AsyncFunc[R], *args: object) -> R:
        """
        Runs async work to completion through the execution portal.

        A callable is invoked on the portal loop and its awaitable result awaited. A
        bare awaitable is only awaited.

        Args:

            value: An async callable to invoke on the portal loop, or an awaitable to
                await directly.

            args: Positional arguments forwarded to a callable ``value``.

        Returns:

            The value the awaited work resolves to.

        """
        self._require_open("run work in")

        if isawaitable(value):
            result = self.portal.call(lambda: value)
        else:
            result = self.portal.call(value, *args)

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

            InvalidPipelineError: If ``is_async`` is unset and ``value``'s only close,
                or its ``cleanup``, is async.

        """
        bridge = partial(self._run_bounded, self.portal) if is_async else None
        args = (self.queue_callback, value, cleanup)
        _queue_close(*args, is_async=is_async, bridge=bridge)

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
        cm = build_context_manager(plan)
        lifecycle = _PortalLifecycle(cm, timeout, self._cleanup_errors)
        return self.enter_context(self.portal.wrap_async_context_manager(lifecycle))

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

    def _unwind(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> tuple[BaseException | None, bool]:
        """
        Unwinds the exit stack, starting with the worker pool.

        Each portal close on the stack is bounded by the global shutdown timeout.

        Returns:

            The exception a context manager replaced the primary error with, if any,
            and whether the primary error was suppressed.

        """
        raised: BaseException | None = None
        suppressed = False
        self._stack.push(self._pools)

        try:
            suppressed = bool(self._stack.__exit__(exc_type, exc, traceback))
        except Exception as error:  # noqa: BLE001 (re-raised by _report_shutdown)
            raised = error

        return raised, suppressed

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
            raised, suppressed = self._unwind(exc_type, exc, traceback)
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
        Opens a seed as the sync stream this execution reads.

        Args:

            seed: Items for the workflow output's open input. A seed that is both sync-
                and async-iterable is read synchronously. The execution closes the seed
                when it exits.

        Raises:

            InvalidPipelineError: Before any item is read, if a seed read
                synchronously only has an async close.

        """
        resolved = self.run_async(seed) if is_awaitable(seed) else seed

        if isinstance(resolved, Iterable) or not isinstance(resolved, AsyncIterable):
            # an unbound T | Iterable[T] defeats listize's overloads
            iterator = stream = iter(cast("Iterable[T]", listize(resolved)))
            call_if_distinct(self.register_owned, resolved, iterator)
            self.register_owned(iterator)
        else:
            iterator = aiter(resolved)
            call_if_distinct(self.register_owned, resolved, iterator, is_async=True)
            stream = self._drain_owned(iterator)

        return stream

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        return ResourceView(map_values(self.acquire, self._require_bindings(binding)))

    def _map_stream(
        self, call: TrackedCall[object], envelopes: EnvelopeStream[object]
    ) -> EnvelopeStream[object]:
        """Maps a node's per-item call over its envelopes once the consumer pulls."""
        self._require_open("map items in")
        yield from self._pool.flat_map(call, envelopes, ordered=self.settings.ordered)

    def _drain_item(
        self,
        interface: AsyncInterface[AsyncIterator[object]],
        context: Context | None,
        extra: dict[str, object],
        item: object,
    ) -> Iterator[object]:
        """
        Runs an async-only mappable node's call for one input item via the portal.

        Pulls the node's per-item results one at a time. The result stream is closed on
        the portal loop once it is drained or closed early.
        """
        results = aiter(interface.item_call(item, context, **extra))

        try:
            yield from self._to_sync(results)
        finally:
            self._maybe_close_async(results)

    def _build_item_stream(
        self,
        context: Context | None,
        node: PreparedNode,
        stream: EnvelopeStream[object],
        /,
        **extra: object,
    ) -> EnvelopeStream[object]:
        """
        Builds a mappable node's envelope stream by running its call once per item.

        When the settings allow concurrency, runs several item calls at once on the
        run's worker pool.
        """
        node_id = node.node.id
        policy = self.settings.sync_policy
        interface = node.sync_interface

        if policy.workers is None or interface is None:
            if interface is None:
                name = node.module.name
                adapted = require_non_null(node.async_interface, NO_PIPE_MSG, name)
                call = partial(self._drain_item, adapted, context, extra)
                identity = adapted.identity
            else:
                call = build_item_call(context, node, interface, **extra)
                identity = interface.identity

            envelopes = _gen_item_stream(call, node_id, identity, stream)
        else:
            call = build_item_call(context, node, interface, **extra)
            identity = interface.identity
            args = (call, policy.executor)
            tracked = build_tracked_call(*args, node_id=node_id, identity=identity)
            envelopes = self._map_stream(tracked, stream)

        return envelopes

    def _build_whole_stream(
        self,
        run: _RunStream[object],
        node: PreparedNode,
        extras: ExecutionExtras[EnvelopeStream[object]],
        named: PortMap[object],
        stream: EnvelopeStream[object],
    ) -> EnvelopeStream[object]:
        """
        Builds the output stream of a node that reads its whole input in one call.

        The pipe reads bare values. Each value it passes through keeps its envelope.
        """
        node_id = node.node.id

        if (interface := node.sync_interface) is None:
            name = node.module.name
            adapted = require_non_null(node.async_interface, NO_PIPE_MSG, name)
            provenance = NodeProvenance.from_identity(node_id, adapted.identity)
            gen_values = provenance.gen_values
            extra = extras.map_kwargs(gen_values, named)
            values = gen_values(stream, adapted.item_normalizer)
            araw = adapted.call(values, run.context, **extra)
            astream = aiter(araw)
            call_if_distinct(self.register_owned, araw, astream, is_async=True)
            results = self._drain_owned(astream)
        else:
            args = (node_id, interface.identity)
            provenance: NodeProvenance[object] = NodeProvenance.from_identity(*args)
            gen_values = provenance.gen_values
            extra = extras.map_kwargs(gen_values, named)
            values = gen_values(stream, interface.item_normalizer)
            raw = interface.call(values, run.context, **extra)
            results = iter(raw)
            call_if_distinct(run.add, raw, results)
            non_generator = not isgenerator(results)

            if non_generator and resolve_closer(results, is_async=False) is not None:
                results = _Owned(results)

            run.add(results)

        return provenance.gen_envelopes(results)

    def _maybe_close_async(self, value: object) -> None:
        """Closes a value produced on the portal loop if it has a close."""
        bridge = partial(self._run_bounded, self.portal)
        _maybe_close(value, is_async=True, bridge=bridge)

    def _gen_branches(
        self,
        run: _RunStream[object],
        interface: SyncInterface[Cascade],
        values: Iterator[object],
        /,
        **extra: object,
    ) -> Iterator[tuple[Iterator[object], Func[None]]]:
        """
        Runs a splitter and pairs each branch with its closer.

        Each branch closes once, however many owners close it. It comes paired with its
        close to match the async-only splitter's branches.
        """
        cascade = interface.call(values, run.context, **extra)
        run.add(cascade)

        for stream in cascade:
            owned = _Owned(stream)
            run.add(owned)
            yield owned, partial(_maybe_close, owned)

    def _adapt_interface(
        self,
        run: _RunStream[object],
        interface: AsyncInterface[AsyncCascade],
        values: Iterator[object],
        /,
        **extra: object,
    ) -> Iterator[tuple[Iterator[object], Func[None]]]:
        """
        Runs an async-only splitter and pairs each branch with its closer.

        The splitter's branches are read through the execution portal. Each branch
        comes paired with its close since the sync view of an async branch only reads
        it and cannot close it.
        """
        acascade = aiter(interface.call(values, run.context, **extra))

        for abranch in self._drain_owned(acascade):
            abranch_iter = aiter(abranch)
            self.register_owned(abranch_iter, is_async=True)
            close = partial(self._maybe_close_async, abranch_iter)
            yield self._to_sync(abranch_iter), close

    def _build_cascade(
        self,
        run: _RunStream[object],
        node: PreparedSplitter,
        extras: ExecutionExtras[EnvelopeStream[object]],
        named: PortMap[object],
        stream: EnvelopeStream[object],
        *,
        demand: Counter[PortKey],
    ) -> OutputPorts[object]:
        """
        Builds the output stream for each splitter port the run reads.

        Unwraps the input envelopes and feeds their values to the splitter. Afterwards,
        wraps the splitter output items back into their original envelopes. A branch
        nothing reads is closed before anything is read.

        Args:

            run: The run that owns the node's streams, with its context and limiter.
            node: The splitter being run.
            extras: The keyword arguments the execution adds to the splitter's call.
            named: The splitter's named input streams, keyed by port name.
            stream: The splitter's primary input stream.

        Kwargs:

            demand: The number of readers per port.

        Returns:

            The envelope stream for each port the run reads, keyed by port.

        Raises:

            InvalidPipelineError: If the splitter yields a different number of branches
                than it declares.

        """
        node_id = node.node.id
        active = [port for port in node.output_ports if demand[node_id, port]]
        tee = Tee(stream, max_lag=settings.branch_buffer)
        feed = tee.branch()
        parents = {port: tee.branch() for port in active}
        run.add(tee, feed, *parents.values())
        values = _unwrap(feed)

        extra = extras.map_kwargs(_unwrap, named)
        native = (interface := node.sync_interface) is not None

        if interface is None:
            name = node.module.name
            _interface = require_non_null(node.async_interface, NO_PIPE_MSG, name)
            args = (run, _interface, values)
            _branches = self._adapt_interface(*args, **extra)
        else:
            args = (run, interface, values)
            _branches = self._gen_branches(*args, **extra)

        branches = list(islice(_branches, node.splits + 1))
        ports: OutputPorts[object] = {}
        node.validate_branches(*branches)

        for port, (branch, close) in zip(node.output_ports, branches, strict=True):
            if (parent := parents.get(port)) is None:
                close()
            elif native:
                envelopes = _wrap(branch, parent)
                ports[port] = auto_close(envelopes, branch, parent)
            else:
                ports[port] = _wrap(branch, parent)

        return ports

    def _register_port(
        self,
        steps: SyncExecSteps[object],
        run: _RunStream[object],
        key: PortKey,
        stream: EnvelopeStream[object],
        readers: int,
    ) -> None:
        """
        Registers a port's stream so that each of its readers gets its own.

        A port with several readers is shared. Each reader gets its own branch, and
        every reader except the first gets a deep copy of each item.
        """
        run.add(stream)

        if readers == 1:
            steps[key] = [stream]
        else:
            max_lag = settings.branch_buffer
            tee = Tee(stream, isolate=True, max_lag=max_lag)
            steps[key] = [tee.branch() for _ in range(readers)]
            run.add(tee, *steps[key])

    def _build_stream(
        self,
        plan: ExecutionPlan,
        steps: SyncExecSteps[object],
        run: _RunStream[object],
        node_id: NodeId,
        *,
        demand: Counter[PortKey],
        seed: Iterable[object] | None = None,
    ) -> OutputPorts[object]:
        """
        Builds a node's lazy output streams from its input streams.

        A mappable node (loopable, with no secondary input stream) runs once per item.
        When the settings allow concurrency, a mappable node with a synchronous
        implementation runs its items in the run's worker pool. A splitter builds one
        stream per branch it is read from. Any other node reads its whole input in one
        call. ``seed`` enters the node as new items.

        Args:

            plan: The prepared workflow being run.
            steps: The streams each upstream port has left to hand out.
            run: The run that owns the node's streams.
            node_id: Id of the node to build.

        Kwargs:

            demand: The number of readers per port.
            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy output envelope streams, keyed by output port.

        """
        node = plan.nodes[node_id]
        roots = None if seed is None else gen_result_envelopes(node_id, seed)
        inputs = self._resolve_node_inputs(steps, node.incoming, roots)
        named, others = inputs.named, inputs.others
        bind = self._bind_resources
        resources = bind(node.resources) if node.resources else None

        if inputs.stream is None:
            _stream = iter(DEFAULT_ENVELOPES if others is None else ())
        else:
            _stream = inputs.stream

        match node:
            case PreparedSplitter():
                extras = ExecutionExtras(others=others, resources=resources)
                args = (run, node, extras, named, _stream)
                ports = self._build_cascade(*args, demand=demand)
            case PreparedNode():
                embed = self._select_embed(node, self._to_sync)
                extras = ExecutionExtras(
                    others=others, resources=resources, embed=embed
                )

                if node.is_mappable:
                    args = (run.context, node, _stream)
                    stream = self._build_item_stream(*args, **named, **extras.kwargs)
                else:
                    args = (run, node, extras, named, _stream)
                    stream = self._build_whole_stream(*args)

                ports = {OUT: stream}

        return ports

    def _run_plan(
        self,
        plan: ExecutionPlan,
        output: OutputName,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
        context: Context | None,
    ) -> EnvelopeStream[T]:
        """
        Builds the envelope stream for a plan's workflow output.

        The run closes every node stream it built when its output closes, last built
        first. The execution closes the run when it exits. It also closes the streams at
        once when building a later node fails.
        """
        endpoint = plan.require_output(output)
        steps: SyncExecSteps[object] = {}
        demand = plan.get_port_demand(output)
        run: _RunStream[_ItemEnvelope[T]] = _RunStream(context)
        self.queue_callback(run.close)

        if self.settings.sync_policy.executor is Executor.PROCESS:
            require_process_safe(plan, output, context)

        try:
            stream = None if seed is None else self._open_seed(seed)
            args = (plan, steps, run)

            for node_id, node_seed in plan.gen_build_order(output, seed=stream):
                build = self._build_stream
                ports = build(*args, node_id, demand=demand, seed=node_seed)

                for port, port_stream in ports.items():
                    key = (node_id, port)
                    self._register_port(steps, run, key, port_stream, demand[key])

            endpoint_stream = steps[endpoint.port_key].pop()
            run.add(endpoint_stream)
        except BaseException:
            run.close()
            raise

        return run

    def run_envelopes(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> EnvelopeStream[T]:
        """
        Builds an envelope stream for a plan's workflow output.

        Each envelope is an item plus run-local identity. Otherwise it behaves like
        ``run``.

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

            The envelope stream produced at the selected workflow output.

        Raises:

            InvalidPipelineError: If any of these hold:

                - ``plan`` does not expose ``output``.
                - No ``seed`` is given and a node needs one, or the plan has no nodes.
                - A ``seed`` is given but ``output`` does not have exactly one node for
                  it to feed.
                - A workflow input is missing or invalid.
                - The process executor is chosen and a node cannot be sent to a worker
                  process.

        """
        self._require_open("run")
        resolved, context = self._resolve_plan(plan)

        if resolved.workflow.is_empty:
            values = self._open_seed(resolved.require_seed(seed, output))
            stream: EnvelopeStream[T] = map(_ItemEnvelope, values)
        else:
            stream = self._run_plan(resolved, output, seed, context)

        return stream

    def run(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> Iterator[T]:
        """
        Builds the item stream for a plan's workflow output.

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

            The output item stream.

        Raises:

            InvalidPipelineError: If any of these hold:

                - ``plan`` does not expose ``output``.
                - No ``seed`` is given and a node needs one, or the plan has no nodes.
                - A ``seed`` is given but ``output`` does not have exactly one node for
                  it to feed.
                - A workflow input is missing or invalid.
                - The process executor is chosen and a node cannot be sent to a worker
                  process.

        """
        stream = self.run_envelopes(plan, output, seed=seed)
        values = auto_close(map(_get_value, stream), stream)
        self.queue_callback(values.close)
        return values


__all__ = ["SyncExecution"]
