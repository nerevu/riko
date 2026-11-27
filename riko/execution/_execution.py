# vim: sw=4:ts=4:expandtab
"""
Shared state and plan checks for the private sync/async executions.

An execution plan is a reusable structural snapshot of a workflow. Running it creates a
one-shot sync or async execution. Each keeps the exit stack and sync/async bridge that
scope a run's acquired resources and adapted work.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, ExitStack, contextmanager
from contextvars import ContextVar
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, Never, Self, overload

from attrs import Factory, define, field

from riko.bado._backend import CapacityLimiter, Event, lowlevel
from riko.bado._util import async_runner, asyncify
from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._funcutils import map_values, resolve_default
from riko.definitions._context import Context
from riko.definitions._settings import DEF_EXECUTION_SETTINGS, ExecutionSettings
from riko.types._workflow import parse_port

from ._adapt import select_embed
from ._prepared import NodeInputs
from ._provenance import PLACEHOLDER

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Mapping
    from contextlib import AbstractContextManager
    from types import TracebackType

    from anyio import CapacityLimiter as Limiter
    from anyio.from_thread import BlockingPortal
    from anyio.lowlevel import RunVar

    from riko.definitions._resource_definition import Resource
    from riko.types._events import EventSink
    from riko.types._feed import AsyncEnvelopeStream, EnvelopeStream, _ItemEnvelope
    from riko.types._frozendict import FrozenWorkflowEdges
    from riko.types._workflow import OutputName, PortKey, PortName, ResourceName
    from riko.types._wrappers import AnyModuleWrapper, Func

    from ._adapt import Drain, WorkerCall
    from ._prepared import ExecutionPlan, PreparedNode

type SyncExecSteps[T] = dict[PortKey, list[EnvelopeStream[T]]]
type AsyncExecSteps[T] = dict[PortKey, list[AsyncEnvelopeStream[T]]]
type Acquisition[T] = _Acquired[T] | _FailedAcquisition
type Acquisitions = dict[Resource[Any], Acquisition[Any]]

_budgets: RunVar[_ThreadBudget] | None = (
    None if lowlevel is None else lowlevel.RunVar("node_threads")
)
_on_node_thread: ContextVar[bool] = ContextVar("on_node_thread", default=False)


class _NullEventSink:
    """Discards every emitted event."""

    __slots__ = ()

    def emit(self, event: object) -> None:
        """
        Discards an emitted execution event.

        Args:

            event: The event value produced during a run.

        """


_NULL_EVENT_SINK = _NullEventSink()
DEFAULT_ENVELOPES: tuple[_ItemEnvelope[object], ...] = (PLACEHOLDER,)
SHUTDOWN_MSG = "shutting down the execution"


@define(frozen=True, slots=True)
class _Acquired[T]:
    """Holds a successfully acquired resource value for single-flight replay."""

    value: T

    def unwrap(self) -> T:
        """Replays the acquired value."""
        return self.value


@define(frozen=True, slots=True)
class _FailedAcquisition:
    """Holds a failed acquisition so repeated use replays the same error."""

    error: BaseException

    def unwrap(self) -> Never:
        """Replays the acquisition's original error."""
        raise self.error


@define(eq=False)
class _ThreadBudget:
    """
    Shares one event loop's node threads among the executions running on it.

    A run takes every thread it may hold at once before it reads anything. No run waits
    for a thread while holding threads another run is waiting for.
    """

    total: int
    available: int = field(
        default=Factory(lambda self: self.total, takes_self=True), init=False
    )
    _restored: Event = field(factory=Event, init=False)

    async def reserve(self, count: int) -> _Reservation:
        """Waits until ``count`` node threads are free, then takes them all at once."""
        while count and self.available < count:
            await self._restored.wait()

        self.available -= count
        return _Reservation(self, count)

    def restore(self, count: int) -> None:
        """Gives back ``count`` node threads and wakes the runs waiting for them."""
        self.available += count
        restored, self._restored = self._restored, Event()
        restored.set()


@define(eq=False)
class _Reservation:
    """
    The node threads one run holds until its output stream closes.

    Its ``limiter`` caps the run's node threads at the number it reserved. It is built
    on the event loop that reserves it.
    """

    budget: _ThreadBudget
    count: int
    held: bool = field(default=True, init=False)
    limiter: Limiter = field(
        init=False,
        default=Factory(
            lambda self: CapacityLimiter(max(self.count, 1)), takes_self=True
        ),
    )

    def release(self) -> None:
        """Gives the threads back to the budget. A repeated call does nothing."""
        if self.held:
            self.held = False
            self.budget.restore(self.count)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


def _resolve_thread_budget() -> _ThreadBudget:
    """Finds the running event loop's node-thread budget and starts it on first use."""
    if _budgets is None:
        msg = "anyio is required to run async executions"
        raise RuntimeError(msg)
    elif (budget := _budgets.get(None)) is None:
        budget = _ThreadBudget(config.node_threads)
        _budgets.set(budget)

    return budget


def _event_sink[S: (ExitStack, AsyncExitStack)](self: _BaseExecution[S]) -> EventSink:
    return resolve_default(self.settings.event_sink, _NULL_EVENT_SINK)


events = Factory(_event_sink, takes_self=True)


@define(eq=False)
class _BaseExecution[S: (ExitStack, AsyncExitStack)]:
    """
    Shares the state and checks both executions run, plus their one worker-thread call.

    That covers the context and settings, the closed-state guard, synchronous
    exit-stack entry, cleanup-error reporting, the resolved-resource cache, resource-
    binding checks, input wiring, node-thread reservations, and ``run_sync``.
    ``run_sync`` runs a blocking callable on a worker thread from whichever event loop
    is running.
    """

    context: Context | None = None
    settings: ExecutionSettings = field(default=DEF_EXECUTION_SETTINGS, kw_only=True)
    events: EventSink = field(default=events, kw_only=True)
    _stack: S = field(init=False)
    _closing: bool = field(default=False, init=False)
    _cleanup_errors: list[Exception] = field(factory=list, init=False)
    _acquired: Acquisitions = field(factory=dict, init=False)
    _reservations: list[_Reservation] = field(factory=list, init=False)
    is_async: ClassVar[bool]

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

    def _resolve_plan(
        self, plan: ExecutionPlan
    ) -> tuple[ExecutionPlan, Context | None]:
        """
        Resolves the inputs and context a plan's nodes run under.

        The run's context is derived from the execution's. The execution's own context
        stays as given, so a later run of another plan resolves that plan's defaults
        rather than this run's values.
        """
        if plan.inputs is None:
            given = None if self.context is None else self.context.inputs
            _inputs = plan.workflow.resolve_inputs(given)
            _plan = plan if _inputs is None else plan.with_inputs(_inputs)
        else:
            _plan = plan

        if _plan.inputs is None:
            context = self.context
        else:
            given_context = resolve_default(self.context, Context())
            context = given_context.replace(inputs=_plan.inputs)

        return _plan, context

    @contextmanager
    def _record_cleanup_errors(self) -> Generator[None]:
        """Records an error the block raises during cleanup."""
        try:
            yield
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

    def _record_cleanup_error(self, func: Func[object], *args: object) -> None:
        """Runs a cleanup callback and saves its failure for the shutdown report."""
        with self._record_cleanup_errors():
            func(*args)

    def queue_callback(self, func: Func[object], *args: object) -> None:
        """
        Registers a synchronous ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(self._record_cleanup_error, func, *args)

    async def run_sync[R, **P](
        self, func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """
        Runs a blocking sync callable on a worker thread from the running event loop.

        Args:

            func: A synchronous callable to run off the event loop.
            args: Positional arguments forwarded to ``func``.

        Kwargs:

            kwargs: Keyword arguments forwarded to ``func``.

        Returns:

            The value ``func`` returns.

        """
        self._require_open("run work in")
        return await asyncify(func, *args, **kwargs)

    async def _reserve_threads(self, demand: int, output: OutputName) -> _Reservation:
        """
        Reserves every node thread a run may hold at once before it reads anything.

        Args:

            demand: The max number of node threads the run may hold at once.
            output: The name of the workflow output being run.

        Returns:

            The run's reservation. It is released when its output stream closes or the
            execution shuts down.

        Raises:

            InvalidPipelineError: If ``demand`` exceeds the event loop's node-thread
                budget, or what this execution's open output streams leave free, or if
                the run is read from a node thread and too few threads are free.

        """
        budget = _resolve_thread_budget()
        self._reservations[:] = [r for r in self._reservations if r.held]
        held = sum(r.count for r in self._reservations)
        kind = "an async" if self.is_async else "a synchronous"

        if demand > budget.total:
            msg = (
                f"workflow output {output!r} may hold {demand} threads at once for "
                f"modules without {kind} implementation. The node-thread budget is "
                f"{budget.total}. Raise RIKO_NODE_THREADS, or shorten the chain of "
                "such modules."
            )
            raise InvalidPipelineError(msg)
        elif held + demand > budget.total:
            msg = (
                f"workflow output {output!r} may hold {demand} threads at once for "
                f"modules without {kind} implementation. This execution's open output "
                f"streams already hold {held} of the node-thread budget of "
                f"{budget.total}. Close them first, or raise RIKO_NODE_THREADS."
            )
            raise InvalidPipelineError(msg)
        elif _on_node_thread.get() and budget.available < demand:
            msg = (
                f"workflow output {output!r} runs inside a module without an async "
                "implementation, for example as a nested stored workflow. It may hold "
                f"{demand} threads at once, but only {budget.available} of the "
                f"node-thread budget of {budget.total} are free. It cannot wait for "
                "threads its parent holds, so raise RIKO_NODE_THREADS."
            )
            raise InvalidPipelineError(msg)

        reservation = await budget.reserve(demand)

        if demand:
            try:
                self.enter_context(reservation)
            except BaseException:
                reservation.release()
                raise

            self._reservations.append(reservation)

        return reservation

    async def _run_on_node_thread[R, **P](
        self,
        runner: async_runner,
        func: Callable[P, R | Awaitable[R]],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Runs a node's blocking step on one of the run's node threads."""
        self._require_open("run work in")
        token = _on_node_thread.set(True)

        try:
            result = await runner(func, *args, **kwargs)
        finally:
            _on_node_thread.reset(token)

        return result

    def _worker(self, limiter: CapacityLimiter | None = None) -> WorkerCall:
        return partial(self._run_on_node_thread, asyncify.using(limiter=limiter))

    def _select_embed(
        self, node: PreparedNode, to_sync: Drain[object]
    ) -> AnyModuleWrapper | None:
        """
        Selects a loop node's embed for the mode its host pipe runs in.

        Args:

            node: The prepared node whose embed to select.
            to_sync: Pulls an async-only embed's output stream under a sync host.

        Returns:

            The embed's callable for the host pipe's mode, else ``None`` when the node
            has no embed.

        """
        module = node.module

        if node.embed is None:
            embed = None
        else:
            is_async = self.is_async and module.async_pipe is not None

            embed = select_embed(
                node.embed,
                host_is_async=is_async or module.sync_pipe is None,
                run_sync=self.run_sync,
                to_sync=to_sync,
            )

        return embed

    @overload
    def enter_context(
        self, cm: AbstractContextManager[BlockingPortal]
    ) -> BlockingPortal: ...
    @overload
    def enter_context[V](self, cm: AbstractContextManager[V]) -> V: ...
    def enter_context[V](
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

    def _require_bindings(
        self, binding: Mapping[str, ResourceName]
    ) -> dict[str, Resource[object]]:
        """Requires the context to provide every resource a node binds, by slot."""
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            msg = f"resource(s) {names} not provided by the context"
            raise InvalidPipelineError(msg)

        return map_values(available.__getitem__, binding)

    def _resolve_node_inputs[V](
        self,
        steps: Mapping[PortKey, list[V]],
        incoming: FrozenWorkflowEdges,
        seed: V | None,
    ) -> NodeInputs[V]:
        """
        Routes upstream port outputs into a node's input ports.

        The default input port receives the input stream. ``seed`` supplies it only when
        no edge targets that port. Edges into named ``in:<name>`` ports become the named
        streams, and are keyed by their name. Edges into positional ``in:<n>`` ports
        become the positional streams, and are ordered by ``n``.

        Args:

            steps: The streams each upstream port has left to hand out.
            incoming: The stream edges that target the node.
            seed: The items fed to the node's open input, if any.

        Returns:

            The node's input stream (``None`` when neither an edge nor ``seed`` fills
            the default port), its named streams, and its positional streams.

        """
        stream = seed
        indexed: list[tuple[int, V]] = []
        named: dict[PortName, V] = {}

        for edge in incoming:
            input_port = parse_port(edge.target_port)
            output_stream = steps[edge.source_key].pop()

            if input_port.is_default:
                stream = output_stream
            elif input_port.index is not None:
                indexed.append((input_port.index, output_stream))
            elif input_port.name is not None:
                named[input_port.name] = output_stream

        ordered = sorted(indexed, key=lambda item: item[0])
        others = [_stream for _, _stream in ordered] if ordered else None
        return NodeInputs(stream, named, others)
