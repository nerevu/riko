# vim: sw=4:ts=4:expandtab
"""
Private synchronous execution that runs a prepared workflow.

It owns one exit stack for a run's acquired resources, a lazily started blocking
portal for async-only components, and the run's one worker pool.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Iterator, Mapping
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import ExitStack
from functools import cached_property, partial
from inspect import GEN_CREATED, getgeneratorstate, isawaitable
from operator import attrgetter
from typing import TYPE_CHECKING, Literal, Self, cast, overload

from attrs import define, field

from riko.bado._backend import fail_after, start_blocking_portal
from riko.bado._util import maybe_closing, run_bridged
from riko.base._config import DEFAULT_OUTPUT
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._funcutils import call_if_distinct, map_values
from riko.base._guards import is_async_callable, is_awaitable
from riko.coercion._sequences import listize
from riko.types._enums import Executor
from riko.types._feed import (
    EnvelopeGenerator,
    EnvelopeStream,
    ItemCall,
    TrackedCall,
    _ItemEnvelope,
)
from riko.types._io import ASYNC_CLEANUP_MSG, resolve_closer
from riko.types._resource import (
    AsyncLifecyclePlan,
    ExternalPlan,
    OwnedPlan,
    SyncLifecyclePlan,
    ValueFactoryPlan,
)
from riko.types._wrappers import require_single_output

from ._adapt import async_drain, require_async_stream, require_stream, select_embed
from ._concurrency import build_item_call, build_tracked_call, require_process_safe
from ._execution import (
    Acquisition,
    SyncExecSteps,
    _Acquired,
    _BaseExecution,
    _FailedAcquisition,
)
from ._pools import _PoolLifetime
from ._prepared import ExecutionExtras
from ._provenance import NodeProvenance, gen_result_envelopes
from ._resource_acquisition import build_context_manager, call_factory
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from anyio.from_thread import BlockingPortal

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._enums import IdentityMode
    from riko.types._io import Closer
    from riko.types._resource import Cleanup, ResourcePlan
    from riko.types._streams import AnyIterable
    from riko.types._workflow import NodeId, OutputName, PortName
    from riko.types._wrappers import AsyncFunc, AsyncModuleWrapperOutput

    from ._adapt import Drain
    from ._prepared import ExecutionPlan, PreparedInterface, PreparedNode

_get_value = attrgetter("value")


def _gen_run_values[T](stream: EnvelopeStream[T]) -> Iterator[T]:
    """Unwraps a run's envelopes and closes the stream when the values are closed."""
    with maybe_closing(stream):
        yield from map(_get_value, stream)


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


# a sync run object owning its node streams, as the async run does, retires this
def _close_tracked[T](envelopes: EnvelopeGenerator[T], closer: Closer) -> None:
    """
    Closes a node's envelope stream, or its pipe's results if nothing read that stream.

    The node's pipe reads the entire input in one call and returns its results as one
    stream. Closing ``envelopes`` closes the pipe's results too, but only once something
    has read from it. Otherwise the pipe's results are closed directly.
    """
    if getgeneratorstate(envelopes) == GEN_CREATED:
        run_bridged(closer)
    else:
        envelopes.close()


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

    @cached_property
    def _async_drain(self) -> Drain[T]:
        """Pulls an async stream item by item through the execution portal."""
        return partial(async_drain, self.run_async)

    def _drain_owned(self, stream: AsyncIterator[T]) -> Iterator[T]:
        """Drains an async iterator this execution owns and closes it at exit."""
        self.register_owned(stream, is_async=True)
        return self._async_drain(stream)

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
            self.register_owned(iterator)
            is_async = False
        else:
            iterator = aiter(resolved)
            stream = self._drain_owned(iterator)
            is_async = True

        call_if_distinct(self.register_owned, resolved, iterator, is_async=is_async)
        return stream

    def _bind_resources(self, binding: Mapping[str, str]) -> ResourceView:
        return ResourceView(map_values(self.acquire, self._require_bindings(binding)))

    def _map_stream(
        self, call: TrackedCall[T], envelopes: EnvelopeStream[T]
    ) -> EnvelopeStream[T]:
        """Maps a node's per-item call over its envelopes once the consumer pulls."""
        self._require_open("map items in")
        yield from self._pool.flat_map(call, envelopes, ordered=self.settings.ordered)

    def _drain_item(
        self,
        interface: PreparedInterface,
        context: Context | None,
        extra: dict[str, object],
        item: T,
    ) -> Iterator[T]:
        """
        Runs an async-only mappable node's call for one input item via the portal.

        Pulls the node's per-item results one at a time. A result stream not completely
        drained is closed on the portal loop.
        """
        raw = interface.item_call(item, context, **extra)
        output = cast("AsyncModuleWrapperOutput[T]", raw)
        results = require_async_stream(output, interface.pipe)
        finished = False

        try:
            yield from self._async_drain(results)
            finished = True
        finally:
            closer = None if finished else resolve_closer(results, is_async=True)

            if closer is not None:
                run_bridged(closer, partial(self._run_bounded, self.portal))

    def _build_item_stream(
        self,
        context: Context | None,
        node: PreparedNode,
        extra: dict[str, object],
        stream: EnvelopeStream[T],
    ) -> EnvelopeStream[T]:
        """
        Builds a mappable node's envelope stream by running its call once per item.

        When the settings allow concurrency, runs several item calls at once on the
        run's worker pool.
        """
        interface = node.sync_interface
        node_id = node.node.id
        identity = interface.identity
        require_single_output(interface.pipe)

        if not interface.native:
            drain = partial(self._drain_item, interface, context, extra)
            envelopes = _gen_item_stream(drain, node_id, identity, stream)
        elif (policy := self.settings.sync_policy).workers is not None:
            call = build_item_call(context, node, **extra)
            args = (call, policy.executor)
            tracked = build_tracked_call(*args, node_id=node_id, identity=identity)
            envelopes = self._map_stream(tracked, stream)
        else:
            call = build_item_call(context, node, **extra)
            envelopes = _gen_item_stream(call, node_id, identity, stream)

        self.register_owned(envelopes)
        return envelopes

    # differs from the async twin until the sync execution owns its streams per run
    def _build_whole_stream(
        self,
        context: Context | None,
        node: PreparedNode,
        extras: ExecutionExtras[EnvelopeStream[T]],
        streams: tuple[EnvelopeStream[T], dict[PortName, EnvelopeStream[T]]],
    ) -> EnvelopeStream[T]:
        """
        Builds the output stream of a node that reads its whole input in one call.

        The pipe reads bare values. Each value it passes through keeps its envelope.
        """
        interface = node.sync_interface
        args = (node.node.id, interface.identity)
        _stream, named = streams

        provenance: NodeProvenance[T] = NodeProvenance.from_identity(*args)
        gen_values = provenance.gen_values
        extra = extras.map_kwargs(gen_values, named)
        values = gen_values(_stream, interface.item_normalizer)
        raw = interface.call(values, context, **extra)

        if interface.native:
            value = cast("Iterator[T] | Iterator[Iterator[T]]", raw)
            stream = require_stream(value, interface.pipe)
            call_if_distinct(self.register_owned, value, stream)
        else:
            avalue = cast("AsyncModuleWrapperOutput[T]", raw)
            astream = require_async_stream(avalue, interface.pipe)
            call_if_distinct(self.register_owned, avalue, astream, is_async=True)
            stream = self._drain_owned(astream)

        envelopes = provenance.gen_envelopes(stream)

        if (closer := resolve_closer(stream, is_async=False)) is not None:
            self.queue_callback(_close_tracked, envelopes, closer)

        return envelopes

    def _build_stream(
        self,
        plan: ExecutionPlan,
        steps: SyncExecSteps[_ItemEnvelope[T]],
        context: Context | None,
        node_id: NodeId,
        *,
        seed: Iterable[T] | None = None,
    ) -> EnvelopeStream[T]:
        """
        Builds one node's lazy output stream from its pre-built input streams.

        A mappable node (loopable, with no secondary input stream) runs once per item.
        When the settings allow concurrency, a mappable node with a synchronous
        implementation runs its items in the run's worker pool. Any other node reads its
        whole input in one call. The seed enters as new items of the node it feeds.

        Args:

            plan: The prepared workflow being run.
            steps: The streams already built for upstream nodes.
            context: The run's context with its resolved input values.
            node_id: Id of the node to build.

        Kwargs:

            seed: The items fed to the node's open input, if any.

        Returns:

            The node's lazy output envelope stream.

        """
        node = plan.nodes[node_id]
        roots = None if seed is None else gen_result_envelopes(node_id, seed)

        args = (steps, node.incoming, roots)
        _stream, named, others = self._resolve_node_inputs(*args, as_stream=iter)
        bind = self._bind_resources
        resources = bind(node.resources) if node.resources else None

        if node.embed is None:
            embed = None
        else:
            embed = select_embed(
                node.embed,
                host_isasync=not node.sync_interface.native,
                run_sync=self.run_sync,
                drain=self._async_drain,
            )

        extras = ExecutionExtras(others=others, resources=resources, embed=embed)

        if node.is_mappable:
            extra = {**named, **extras.kwargs}
            stream = self._build_item_stream(context, node, extra, _stream)
        else:
            streams = (_stream, named)
            stream = self._build_whole_stream(context, node, extras, streams)

        return stream

    def _run_plan(
        self,
        plan: ExecutionPlan,
        output: OutputName,
        seed: T | AnyIterable[T] | Awaitable[T | AnyIterable[T]] | None,
        context: Context | None,
    ) -> EnvelopeStream[T]:
        """
        Builds the envelope stream for a plan's workflow output.

        The execution closes every node stream it built when it exits, last built
        first (the output stream included). It closes even when building a later node
        fails. When a pipe returned a closeable wrapper around its stream (rather than
        the stream itself) it then closes that wrapper too. The caller may close the
        output stream sooner.
        """
        endpoint = plan.require_output(output)
        steps: SyncExecSteps[_ItemEnvelope[T]] = {}

        if self.settings.sync_policy.executor is Executor.PROCESS:
            require_process_safe(plan, output, context)

        stream = None if seed is None else self._open_seed(seed)

        args = (plan, steps, context)

        for node_id, node_seed in plan.gen_build_order(output, seed=stream):
            node_stream = self._build_stream(*args, node_id, seed=node_seed)
            steps[node_id] = node_stream

        return steps[endpoint.node]

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

            The item stream produced at the selected workflow output.

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
        return _gen_run_values(self.run_envelopes(plan, output, seed=seed))


__all__ = ["SyncExecution"]
