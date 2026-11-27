# vim: sw=4:ts=4:expandtab
"""
Private synchronous execution that runs an execution plan.

It holds an exit stack that closes a run's acquired resources, a lazily started
blocking portal for async-only components, and the run's one worker pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
from inspect import isawaitable
from itertools import islice
from operator import attrgetter, itemgetter
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast, overload

from attrs import define, field

from riko.bado._backend import fail_after, move_on_after, start_blocking_portal
from riko.bado._util import as_awaitable, maybe_async, maybe_closing, run_bridged
from riko.bado.itertools import aauto_close
from riko.base._config import DEFAULT_OUTPUT, settings
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._funcutils import call_if_distinct, compose, compose_inner, map_values
from riko.base._guards import (
    ASYNC_CLEANUP_MSG,
    SyncClosable,
    is_async_callable,
    is_awaitable,
)
from riko.base._iterutils import Tee, auto_close, partition, raise_failures
from riko.base._require_guards import require_non_null
from riko.coercion._sequences import listize
from riko.types._enums import Executor
from riko.types._feed import (
    EnvelopeStream,
    ItemCall,
    OutputPorts,
    PortMap,
    _ItemEnvelope,
)
from riko.types._io import resolve_closer
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
    ValuePlan,
)
from riko.types._streams import require_async_stream, require_stream
from riko.types._workflow import OUT

from ._adapt import Bridge, to_async, to_sync
from ._concurrency import build_item_call, build_tracked_call, require_process_safe
from ._execution import (
    DEFAULT_ENVELOPES,
    SHUTDOWN_MSG,
    Acquisition,
    SyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._pools import _PoolLifetime, flat_map
from ._prepared import (
    NO_PIPE_MSG,
    AsyncInterface,
    ExecutionExtras,
    PreparedNode,
    PreparedSplitter,
)
from ._provenance import NodeProvenance, gen_result_envelopes
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Awaitable
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.from_thread import BlockingPortal

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._enums import IdentityMode
    from riko.types._feed import AsyncEnvelopeGenerator
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import AnyIterable, AsyncStreamOf, StreamOf
    from riko.types._workflow import NodeId, OutputName, PortKey
    from riko.types._wrappers import Func

    from ._execution import _Reservation
    from ._prepared import ExecutionPlan


def _unwrap[T](stream: EnvelopeStream[T]) -> auto_close[T]:
    """Unwraps each envelope's value and closes ``stream`` once the values end."""
    return auto_close(map(attrgetter("value"), stream), stream)


def _gen_envelopes[T](
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
        yield from gen_result_envelopes(node_id, call(parent.value), parent, identity)


async def _call_on_loop[R](
    func: Callable[..., R | Awaitable[R]],
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> R:
    """
    Calls ``func`` on the running event loop and awaits an awaitable result.

    A dispatch that never starts leaves no unawaited coroutine behind.
    """
    return await maybe_async(func, *args, **kwargs)


def _wrap(
    values: Iterator[object], stream: EnvelopeStream[object]
) -> EnvelopeStream[object]:
    """Matches each splitter stream value with the input envelope it came from."""
    for value, envelope in zip(values, stream, strict=False):
        yield envelope.with_value(value)


def _close_streams(primary: BaseException | None, *streams: StreamOf[object]) -> None:
    """
    Closes every stream and notes a failed close on ``primary`` when there is one.

    Raises:

        Exception: Whatever the one failing close raises, when there is no ``primary``.
        ExceptionGroup: If several closes fail and there is no ``primary``.

    """
    try:
        auto_close(iter(()), *streams).close()
    except Exception as failure:  # noqa: BLE001 (noted on the primary or re-raised)
        raise_failures("closing the splitter's streams", failure, primary=primary)


def take_streams(
    limit: int, streams: Iterable[StreamOf[object]]
) -> list[StreamOf[object]]:
    """
    Takes up to ``limit`` of a splitter's streams.

    Closes ``streams`` after taking. When taking one fails, closes each stream it took.
    """
    _streams: list[StreamOf[object]] = []

    with maybe_closing(streams):
        try:
            for stream in islice(streams, limit):
                _streams.append(stream)  # noqa: PERF402 (kept on a failed take)
        except BaseException as primary:
            _close_streams(primary, *_streams)
            raise

    return _streams


def _queue_close[T](
    callback: Callable[[Func[None]], object],
    value: T,
    cleanup: Cleanup[T] | Literal[False] | None = None,
    bridge: Callable[[Awaitable[object]], object] | None = None,
) -> None:
    """
    Hands ``callback`` the value's close to run later, if it has one.

    When ``bridge`` is set, prefers value's async close and runs it on its event loop.
    """
    closer = resolve_closer(value, cleanup=cleanup, is_async=bridge is not None)

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
        suppressed = False

        with move_on_after(self._timeout) as scope:
            suppressed = bool(await self._cm.__aexit__(exc_type, exc, traceback))

        if scope.cancelled_caught:
            msg = f"closing the lifecycle took longer than {self._timeout} seconds"
            self._errors.append(TimeoutError(msg))

        return suppressed


async def _agen_from[T](stream: AsyncStreamOf[T]) -> AsyncStreamOf[T]:
    """Passes an async stream's items on without closing it."""
    async for item in stream:
        yield item


@define(eq=False)
class _AsyncNodeOutput(Iterator[_ItemEnvelope[object]]):
    """An async-only node's envelope stream synchronously read through the portal."""

    provenance: NodeProvenance[object]
    results: AsyncStreamOf[object]
    envelopes: auto_close[_ItemEnvelope[object]]

    def __next__(self) -> _ItemEnvelope[object]:
        return next(self.envelopes)

    def close(self) -> None:
        """Closes the synchronous envelope stream and the node's results with it."""
        self.envelopes.close()

    def async_gen_envelopes(self) -> AsyncEnvelopeGenerator[object]:
        """Wraps the node's async results in envelopes on the event loop."""
        return self.provenance.agen_envelopes(_agen_from(self.results))


@define(eq=False)
class _RunStream[T]:
    """
    One run's output stream that closes the streams the run registered with it.

    It also carries the run's context and, when it reads async-only nodes, the node
    threads it reserved on the portal loop. Closing it closes its streams last built
    first, output first. It then returns the run's node threads.

    Only the first close does anything. A run that stops or fails also returns its node
    threads.
    """

    context: Context | None
    _reservation: _Reservation | None = field(default=None, alias="reservation")
    _bridge: Bridge | None = field(default=None, alias="bridge")
    _steps: list[SyncClosable] = field(factory=list, init=False)
    output: object = field(default=None, init=False)
    _closed: bool = field(default=False, init=False)

    @property
    def limiter(self) -> Limiter:
        """Caps the run's node threads at the number it reserved."""
        msg = "the run reserved no node threads"
        return require_non_null(self._reservation, msg).limiter

    @property
    def _output(self) -> StreamOf[T]:
        """The endpoint's stream."""
        if not isinstance(output := self.output, Iterator):
            raise TypeError("the run's output must be an iterator")

        return output

    def add(self, *streams: SyncClosable) -> None:
        """Adds the close-once streams the run built."""
        self._steps.extend(streams)

    def _release(self) -> None:
        """Gives the run's node threads back to the portal loop."""
        reservation, bridge = self._reservation, self._bridge

        if reservation is not None and bridge is not None and reservation.held:
            bridge(maybe_async(reservation.release))

    def __iter__(self) -> Self:
        return self

    def __next__(self) -> T:
        try:
            item = next(self._output)
        except BaseException:
            self._release()
            raise

        return item

    def close(self) -> None:
        """Closes every node stream, last built first, then releases the threads."""
        if not self._closed:
            self._closed = True

            try:
                with ExitStack() as stack:
                    for step in self._steps:
                        stack.callback(step.close)
            finally:
                self._release()


@define(eq=False)
class SyncExecution[T](_BaseExecution[ExitStack]):
    """
    Runs an execution plan synchronously behind one exit stack.

    Async-only components run through a lazily started blocking portal. The
    execution settings decide whether mappable nodes spread their items across
    one shared thread or process pool for the run.

    Examples:

        >>> from contextlib import contextmanager
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
    _lifetime: _PoolLifetime | None = field(default=None, init=False)
    _portal: BlockingPortal | None = field(default=None, init=False)
    is_async: ClassVar[bool] = False

    def _get_lifetime(self) -> _PoolLifetime:
        """Opens the run's one worker pool and shares it with every mapped node."""
        if self._lifetime is None:
            executor, workers = self.settings.sync_policy

            if workers is None:
                action = "open a worker pool in"
                raise PipelineStateError("sequential", action, subject="execution")

            if executor is Executor.THREAD:
                pool_type = ThreadPoolExecutor
            else:
                pool_type = ProcessPoolExecutor

            pool = pool_type(workers)
            grace = self.settings.shutdown_timeout
            lifetime = _PoolLifetime(pool, workers, grace=grace)
            self._lifetime = self._pools.enter_context(lifetime)

        return self._lifetime

    def _open_portal(self) -> None:
        """
        Opens the execution's portal onto its exit stack unless it is already open.

        A run that reads an async-only node or embed opens the portal before it queues
        its own close. The exit stack unwinds last-queued first. The portal stops after
        the run closes. An abandoned run's async streams can still close on the portal.
        """
        if self._portal is None:
            if (portal_cm := start_blocking_portal()) is None:
                msg = "anyio is required to run async components in a sync execution"
                raise RuntimeError(msg)

            self._portal = self.enter_context(portal_cm)

    @property
    def portal(self) -> BlockingPortal:
        self._open_portal()
        return require_non_null(self._portal, "the portal is not open")

    def __enter__(self) -> Self:
        return self

    def _unwind(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """
        Unwinds the exit stack starting with the worker pool.

        Bounds each portal close on the stack by the global shutdown timeout. Logs and
        notes cleanup failures on the remaining error. If a context manager on the stack
        raises, its error replaces ``exc``. Else if one returns true, the stack
        suppresses ``exc``.

        Returns:

            Whether the ``exc`` was suppressed.

        Raises:

            Exception: The cleanup failure, when there is only one and ``exc`` was
                suppressed, is ``None``, or is a ``GeneratorExit``.

            ExceptionGroup: All cleanup failures, when there are several and ``exc``
                was suppressed, is ``None``, or is a ``GeneratorExit``.

        """
        self._stack.push(self._pools)

        try:
            suppressed = bool(self._stack.__exit__(exc_type, exc, traceback))
        except Exception as raised:
            raise_failures(SHUTDOWN_MSG, *self._cleanup_errors, primary=raised)
            raise
        else:
            primary = None if suppressed else exc
            raise_failures(SHUTDOWN_MSG, *self._cleanup_errors, primary=primary)
            return suppressed

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
            suppressed = self._unwind(exc_type, exc, traceback)

        return suppressed

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return self.close(exc_type, exc, traceback)

    async def _await_bounded[R](self, value: Awaitable[R]) -> R:
        """Awaits ``value`` within the shutdown timeout."""
        with fail_after(self.settings.shutdown_timeout):
            result = await value

        return result

    @overload
    def run_async[R](self, value: Awaitable[R], /, *, bounded: bool = False) -> R: ...
    @overload
    def run_async[R, **P](
        self, value: Callable[P, Awaitable[R]], /, *args: P.args, **kwargs: P.kwargs
    ) -> R: ...
    @overload
    def run_async[R, **P](
        self, value: Callable[P, R | Awaitable[R]], /, *args: P.args, **kwargs: P.kwargs
    ) -> R: ...
    def run_async[R, **P](
        self,
        value: Awaitable[R] | Callable[P, R | Awaitable[R]],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """
        Runs work to completion on the execution portal's event loop.

        If ``value`` is callable, calls it on the portal loop with every argument given.
        Awaits the result if it is awaitable. A bare awaitable is only awaited.

        Args:

            value: A sync or async callable to invoke on the portal loop. Or an
                awaitable to await directly.

            args: Positional arguments passed to a callable ``value``.

        Kwargs:

            kwargs: Keyword arguments passed to a callable ``value``. With a bare
                awaitable, ``bounded=True`` marks it as cleanup. The cleanup may run
                while the execution closes, and is bounded by the shutdown timeout.

        Returns:

            The value the work resolves to.

        """
        bounded = isawaitable(value) and kwargs.get("bounded") is True

        if not bounded:
            self._require_open("run work in")

        if isawaitable(value):
            work: Awaitable[R] = value
            dispatch = self._await_bounded if bounded else as_awaitable
            result = self.portal.call(dispatch, work)
        else:
            result = self.portal.call(_call_on_loop, value, args, kwargs)

        return result

    def _await_on_loop[R](self, value: Awaitable[R], /) -> R:
        """
        Awaits ``value`` on the portal loop.

        Cleanup is bounded by the shutdown timeout, so reads stay unbounded until the
        execution starts to close.
        """
        return self.run_async(value, bounded=self._closing)

    def queue_close[R](
        self,
        value: R,
        cleanup: Cleanup[R] | Literal[False] | None = None,
        *,
        is_async: bool = False,
    ) -> None:
        """
        Registers a value to close when the execution exits.

        Args:

            value: The value to close.

        Kwargs:

            cleanup: The cleanup to call with ``value`` in place of its own close, or
                ``False`` to leave it open.

            is_async: Whether ``value`` was produced on the execution's event loop. In
                which case its async close or cleanup runs there within the shutdown
                timeout.

        Raises:

            InvalidPipelineError: If ``is_async`` is unset and ``value``'s only close,
                or its ``cleanup`` is async.

        """
        bridge = self._await_on_loop if is_async else None
        _queue_close(self.queue_callback, value, cleanup, bridge=bridge)

    def _open[R](self, plan: ResourcePlan[R]) -> R:
        match plan:
            case ExternalPlan():
                value = plan.value
            case ValuePlan():
                value = plan.value
                self.queue_close(value, plan.cleanup)
            case ValueFactoryPlan():
                if not plan.is_async and is_async_callable(plan.cleanup):
                    raise InvalidPipelineError(ASYNC_CLEANUP_MSG)

                raw = call_factory(plan)
                value = self.run_async(raw) if is_awaitable(raw) else raw
                self.queue_close(value, plan.cleanup, is_async=plan.is_async)
            case SyncLifecyclePlan():
                portal_cm = build_context_manager(plan)
                value = self.enter_context(portal_cm)
            case AsyncLifecyclePlan():
                timeout = self.settings.shutdown_timeout
                cm = build_context_manager(plan)
                bounded_cm = _PortalLifecycle(cm, timeout, self._cleanup_errors)
                portal_cm = self.portal.wrap_async_context_manager(bounded_cm)
                value = self.enter_context(portal_cm)

        return value

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

    def _to_sync[R](self, stream: AsyncStreamOf[R]) -> to_sync[R]:
        """
        Pulls an async stream item by item through the execution portal.

        Closes ``stream`` on the portal loop. Bounds reads and the close by the shutdown
        timeout only once the execution is closing. The close may run while the
        execution exits.
        """
        return to_sync(self._await_on_loop, stream)

    def _open_seed(
        self, seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]]
    ) -> StreamOf[T]:
        """
        Opens a seed as the sync stream this execution reads.

        Args:

            seed: Items for the workflow output's open input. An awaitable is resolved
                when the run starts. A seed that is both sync- and async-iterable is
                read synchronously. The seed closes once the run is done reading it or
                when the execution exits, whichever is first.

        Raises:

            InvalidPipelineError: Before any item is read, if a seed read
                synchronously only has an async close.

        """
        _input = self.run_async(seed) if is_awaitable(seed) else seed

        if isinstance(_input, Iterable) or not isinstance(_input, AsyncIterable):
            iterator, is_async = iter(cast("Iterable[T]", listize(_input))), False
            stream: StreamOf[T] = auto_close(iterator)
        else:
            iterator, is_async = self.run_async(aiter, _input), True
            stream = self._to_sync(iterator)

        call_if_distinct(self.queue_close, _input, iterator, is_async=is_async)
        self.queue_close(stream)
        return stream

    def _to_async[R](
        self, run: _RunStream[_ItemEnvelope[object]], stream: StreamOf[R]
    ) -> AsyncStreamOf[R]:
        """
        Builds an async stream that pulls a sync stream on node threads.

        Each pull is one trip to a worker thread capped by the run's limiter. The async
        stream closes ``stream`` once it is exhausted or closed.
        """
        return to_async(self._worker(limiter=run.limiter), stream)

    def _drain_item(
        self,
        interface: AsyncInterface[AsyncStreamOf[object]],
        name: str,
        context: Context | None,
        extra: dict[str, object],
        item: object,
    ) -> StreamOf[object]:
        """
        Runs an async-only mappable node's call for one input item via the portal.

        Pulls the node's per-item results one at a time. The result stream is closed on
        the portal loop once it is drained or closed early.
        """
        raw = self.run_async(interface.item_call, item, context, **extra)
        return self._to_sync(require_async_stream(raw, name))

    def _build_envelope_stream(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedNode,
        stream: EnvelopeStream[object],
        named: PortMap[object],
        extras: ExecutionExtras[EnvelopeStream[object]],
        /,
    ) -> EnvelopeStream[object]:
        """
        Builds a mappable node's envelope stream by running its call once per item.

        When the settings allow concurrency, runs several item calls at once on the
        run's worker pool. The envelope stream closes ``stream``.
        """
        node_id = node.node.id
        context = run.context
        extra = {**named, **extras.kwargs}
        policy = self.settings.sync_policy
        interface = node.sync_interface

        if policy.workers is None or interface is None:
            if interface is None:
                name = node.module.name
                adapted = require_non_null(node.async_interface, NO_PIPE_MSG, name)
                call = partial(self._drain_item, adapted, name, context, extra)
                identity = adapted.identity
            else:
                call = build_item_call(context, node, interface, **extra)
                identity = interface.identity

            envelopes = _gen_envelopes(call, node_id, identity, stream)
        else:
            self._require_open("map items in")
            call = build_item_call(context, node, interface, **extra)
            args = (call, policy.executor)
            identity = interface.identity
            tracked_call = build_tracked_call(*args, node_id=node_id, identity=identity)
            ordered = self.settings.ordered
            fargs = (tracked_call, stream)
            envelopes = flat_map(*fargs, ordered=ordered, opener=self._get_lifetime)

        return auto_close(envelopes, stream)

    def _run_async_node(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedNode,
        stream: EnvelopeStream[object],
        named: PortMap[object],
        extras: ExecutionExtras[EnvelopeStream[object]],
        /,
    ) -> EnvelopeStream[object]:
        """
        Streams an async-only node's output stream.

        Calls the pipe, pulls its async output, and closes the output and the pipe's
        primary input all on the portal loop. Reads sync input streams on the run's node
        threads. Reads an input that is another async-only node's output on the loop.

        Args:

            run: The run the node is built in, with its context and limiter.
            node: The async-only node being run.
            stream: The node's primary input stream.
            named: The streams wired to the node's named input ports.
            extras: Keyword arguments the execution adds to the node's call.

        Returns:

            The node's envelope stream.

        """
        name = node.module.name
        interface = require_non_null(node.async_interface, NO_PIPE_MSG, name)
        provenance = NodeProvenance.from_identity(node.node.id, interface.identity)
        gen_values = provenance.gen_values

        _to_async = partial(self._to_async, run)
        named_values = extras.map_inputs(compose(_to_async, gen_values), named)
        extra = extras.build_kwargs(named_values)
        normalizer = interface.item_normalizer

        if isinstance(stream, _AsyncNodeOutput):
            upstream = stream.async_gen_envelopes()
            values = provenance.agen_values(upstream, normalizer)
        else:
            values = _to_async(gen_values(stream, normalizer))

        raw = self.run_async(interface.call, values, run.context, **extra)
        astream = require_async_stream(raw, name)
        results = aauto_close(astream, values, *named_values.streams)
        pulled = self._to_sync(results)
        envelopes = auto_close(provenance.gen_envelopes(pulled), pulled, stream)
        return _AsyncNodeOutput(provenance, results, envelopes)

    def _build_splitter_ports(
        self,
        run: _RunStream[_ItemEnvelope[object]],
        node: PreparedSplitter,
        stream: EnvelopeStream[object],
        named: PortMap[object],
        extras: ExecutionExtras[EnvelopeStream[object]],
        /,
        *,
        demand: Counter[PortKey],
    ) -> OutputPorts[object]:
        """
        Builds a stream for each splitter port the run reads.

        Each output item keeps its input item's envelope. Closes ports nothing reads.
        Feeds one copy of the input stream to the splitter and one to each input reader.
        Closing the run closes the copies and the input readers.

        Args:

            run: The run the node is built in, with its context and limiter.
            node: The splitter being run.
            stream: The splitter's primary input stream.
            named: The splitter's named input streams, keyed by port name.
            extras: Keyword arguments the execution adds to the splitter's call.

        Kwargs:

            demand: The number of readers per port.

        Returns:

            The envelope stream for each port the run reads, keyed by port.

        Raises:

            InvalidPipelineError: If the splitter yields a different number of streams
                than it declares.

            TypeError: If a value the splitter yields is not a stream.

        """
        node_id = node.node.id
        active = (port for port in node.output_ports if demand[node_id, port])
        tee = Tee(stream, max_lag=settings.branch_buffer)
        feed = tee.branch()
        parents = {port: tee.branch() for port in active}
        run.add(tee, *parents.values())
        _values = _unwrap(feed)
        named_values = extras.map_inputs(_unwrap, named)
        limit = node.splits + 1

        name = node.module.name

        if (interface := node.sync_interface) is None:
            _interface = require_non_null(node.async_interface, NO_PIPE_MSG, name)
            _to_async = partial(self._to_async, run)
            adapters = named_values.map(_to_async)
            values = _to_async(_values)
            adapted = (*adapters.streams, values)
            run.add(_values, *named_values.streams, *map(self._to_sync, adapted))
            extra = extras.build_kwargs(adapters)
            raw = self.run_async(_interface.call, values, run.context, **extra)

            _streams = self._to_sync(raw)
            to_sync = compose_inner(self._to_sync, require_async_stream, name)
            require = compose(auto_close, to_sync)
            cascade = map(require, _streams)
        else:
            run.add(_values, *named_values.streams)
            extra = extras.build_kwargs(named_values)

            _streams = interface.call(_values, run.context, **extra)
            require = compose_inner(auto_close, require_stream, name)
            cascade = map(require, _streams)

        streams = take_streams(limit, auto_close(cascade, _streams))

        try:
            node.validate_streams(*streams)
        except InvalidPipelineError as primary:
            _close_streams(primary, *streams)
            raise

        pairs = zip(node.output_ports, streams, strict=True)
        read, unread = partition(compose(parents.__contains__, itemgetter(0)), pairs)

        ports: OutputPorts[object] = {
            port: auto_close(_wrap(_stream, parents[port]), _stream, parents[port])
            for port, _stream in read
        }

        try:
            _close_streams(None, *(_stream for _, _stream in unread))
        except Exception as primary:
            _close_streams(primary, *ports.values())
            raise

        return ports

    def _register_port(
        self,
        steps: SyncExecSteps[object],
        run: _RunStream[_ItemEnvelope[object]],
        key: PortKey,
        stream: EnvelopeStream[object],
        readers: int,
    ) -> None:
        """
        Registers a port's stream so that each of its readers gets its own.

        A port with several readers is shared. Each reader gets its own branch, and
        every reader except the first gets a deep copy of each item.

        Raises:

            TypeError: If the port's stream has no close.

        """
        if not isinstance(stream, SyncClosable):
            raise TypeError(f"port {key!r} must be closable")

        run.add(stream)

        if readers == 1:
            steps[key] = [stream]
        else:
            max_lag = settings.branch_buffer
            tee = Tee(stream, isolate=True, max_lag=max_lag)
            branches = [tee.branch() for _ in range(readers)]
            steps[key] = [*branches]
            run.add(tee, *branches)

    def _build_node_ports(
        self,
        plan: ExecutionPlan,
        steps: SyncExecSteps[object],
        run: _RunStream[_ItemEnvelope[object]],
        node_id: NodeId,
        *,
        demand: Counter[PortKey],
        seed: Iterable[object] | None = None,
    ) -> OutputPorts[object]:
        """
        Builds a node's output ports, each a lazy stream, from its input streams.

        A mappable node (loopable, with no secondary input stream) runs once per item.
        When its settings allow concurrency, a mappable node with a synchronous
        implementation runs its items in the run's worker pool.

        A splitter builds one stream per output port it is read from. Any other node
        reads its whole input in one call as bare values. Each value it passes through
        keeps its envelope. ``seed`` enters the node as new items.

        Args:

            plan: The execution plan being run.
            steps: The streams each upstream port has left to hand out.
            run: The run the node is built in.
            node_id: Id of the node to build.

        Kwargs:

            demand: The number of readers per port.
            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy output envelope streams, keyed by output port.

        """
        node = plan.nodes[node_id]
        roots = None if seed is None else gen_result_envelopes(node_id, seed)
        closables = self._resolve_node_inputs(steps, node.incoming, roots)
        named, others = closables.named, closables.others

        if node.resources:
            bindings = self._require_bindings(node.resources)
            resources = ResourceView(map_values(self.acquire, bindings))
        else:
            resources = None

        if closables.stream is None:
            _envelopes = iter(DEFAULT_ENVELOPES if others is None else ())
        else:
            _envelopes = closables.stream

        match node:
            case PreparedSplitter():
                extras = ExecutionExtras(others=others, resources=resources)
                args = (run, node, _envelopes, named, extras)
                ports = self._build_splitter_ports(*args, demand=demand)
            case PreparedNode():
                embed = self._select_embed(node, self._to_sync)
                extras = ExecutionExtras(
                    others=others, resources=resources, embed=embed
                )

                args = (run, node, _envelopes, named, extras)

                if node.is_mappable:
                    envelopes = self._build_envelope_stream(*args)
                elif (interface := node.sync_interface) is None:
                    envelopes = self._run_async_node(*args)
                else:
                    identity = interface.identity
                    provenance = NodeProvenance.from_identity(node_id, identity)
                    named_values = extras.map_inputs(provenance.gen_values, named)
                    extra = extras.build_kwargs(named_values)
                    normalizer = interface.item_normalizer
                    values = provenance.gen_values(_envelopes, normalizer)
                    raw = interface.call(values, run.context, **extra)

                    results = auto_close(require_stream(raw, node.module.name))
                    envelope_gen = provenance.gen_envelopes(results)
                    closables = (results, values, *named_values.streams)
                    envelopes = auto_close(envelope_gen, *closables)

                ports = {OUT: envelopes}

        return ports

    def build_envelope_stream(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> EnvelopeStream[T]:
        """
        Builds an envelope stream for a plan's workflow output.

        Each envelope is an item plus run-local identity. Otherwise it behaves like
        ``run``. Closing the stream closes every node stream the run built, last built
        first. The execution closes the run when it exits, before it stops the portal.

        It also closes the streams at once when building a later node fails. It reports
        a failed close as a cleanup error at exit. The build error stays primary. A run
        that reads async-only nodes reserves the node threads it may hold at once before
        it reads anything. It returns them when it closes.

        Args:

            plan: The execution plan to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. Omit it
                when the workflow output is self-starting (default: None).

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
                - The run holds more node threads at once than the node-thread budget,
                  or than this execution's open output streams leave free.

        """
        self._require_open("run")
        resolved, context = self._resolve_plan(plan)

        if resolved.workflow.is_empty:
            values = self._open_seed(resolved.require_seed(seed, output))
            items = map(_ItemEnvelope, values)
            envelopes: EnvelopeStream[T] = auto_close(items, values)
        else:
            endpoint = resolved.require_output(output)
            steps: SyncExecSteps[object] = {}
            demand = resolved.get_port_demand(output)
            threads = resolved.get_thread_demand(output, is_async=False)

            if self.settings.sync_policy.executor is Executor.PROCESS:
                require_process_safe(resolved, output, context)

            if resolved.uses_portal(output):
                self._open_portal()
                reservation = self.run_async(self._reserve_threads, threads, output)
            else:
                reservation = None

            bridge = self._await_on_loop
            run: _RunStream[_ItemEnvelope[T]] = _RunStream(context, reservation, bridge)
            self.queue_callback(run.close)

            try:
                stream = None if seed is None else self._open_seed(seed)
                args = (resolved, steps, run)

                for node_id, node_seed in resolved.gen_build_order(output, seed=stream):
                    build = self._build_node_ports
                    ports = build(*args, node_id, demand=demand, seed=node_seed)

                    for port, _stream in ports.items():
                        key = (node_id, port)
                        self._register_port(steps, run, key, _stream, demand[key])

                run.output = steps[endpoint.port_key].pop()
            except BaseException:
                self._record_cleanup_error(run.close)
                raise

            envelopes = run

        return envelopes

    def run(
        self,
        plan: ExecutionPlan,
        output: OutputName = DEFAULT_OUTPUT,
        *,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None = None,
    ) -> StreamOf[T]:
        """
        Builds the item stream for a plan's workflow output.

        Only the selected workflow output's upstream subgraph runs. The returned stream
        is lazy. Consume it inside this execution's ``with`` block so the execution
        closes it.

        Args:

            plan: The execution plan to run.

        Kwargs:

            output: The name of the workflow output to produce.

            seed: Items for the workflow output's open input: one item, an item stream,
                an async item stream, or an awaitable resolving to one of those. Omit it
                when the workflow output is self-starting (default: None).

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
        values = _unwrap(self.build_envelope_stream(plan, output, seed=seed))
        self.queue_callback(values.close)
        return values


__all__ = ["SyncExecution"]
