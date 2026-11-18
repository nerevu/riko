# vim: sw=4:ts=4:expandtab
"""
Shared state and plan checks for the private sync/async executions.

A prepared workflow (an execution plan) is a reusable structural snapshot; running
it creates a one-shot sync or async execution. Each owns the exit stack and sync/async
bridge that scope a run's acquired resources and adapted work. These
types are private to the runtime and belong to no supported surface.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, ExitStack
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, Never, overload

from attrs import Factory, define, field

from riko.bado._util import maybe_async
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.base._funcutils import map_values, resolve_default
from riko.definitions._context import Context
from riko.definitions._inputs import resolve_inputs
from riko.definitions._settings import DEF_EXECUTION_SETTINGS, ExecutionSettings
from riko.types._workflow import parse_port

from ._adapt import select_embed
from ._provenance import PLACEHOLDER

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager

    from anyio.from_thread import BlockingPortal

    from riko.definitions._resource_definition import Resource
    from riko.types._events import EventSink
    from riko.types._feed import AsyncEnvelopeStream, EnvelopeStream, _ItemEnvelope
    from riko.types._frozendict import FrozenWorkflowEdges
    from riko.types._workflow import PortKey, PortName, ResourceName
    from riko.types._wrappers import AnyModuleWrapper, Func

    from ._adapt import Drain
    from ._prepared import ExecutionPlan, PreparedNode

type SyncExecSteps[T] = dict[PortKey, list[EnvelopeStream[T]]]
type AsyncExecSteps[T] = dict[PortKey, list[AsyncEnvelopeStream[T]]]
type Acquisition[T] = _Acquired[T] | _FailedAcquisition
type Acquisitions = dict[Resource[Any], Acquisition[Any]]


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


class NodeInputs[V](NamedTuple):
    """
    The streams wired onto a node's input ports.

    Attributes:

        stream: The stream on the default input port.
        named: The streams on the named input ports, keyed by port name.
        others: The streams on the positional input ports, in port order.

    Examples:

        >>> inputs = NodeInputs(None, {"part": [1]}, None)
        >>> inputs.stream
        >>> list(inputs.named)
        ['part']

    """

    stream: V | None
    named: dict[PortName, V]
    others: list[V] | None


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


def _event_sink[S: (ExitStack, AsyncExitStack)](self: _BaseExecution[S]) -> EventSink:
    return resolve_default(self.settings.event_sink, _NULL_EVENT_SINK)


events = Factory(_event_sink, takes_self=True)


@define(eq=False)
class _BaseExecution[S: (ExitStack, AsyncExitStack)]:
    """
    Shares the state and checks both executions run, plus their one worker-thread call.

    That covers the context and settings, the closed-state guard, synchronous
    exit-stack entry, cleanup-error reporting, the resolved-resource cache,
    resource-binding checks, input wiring, and ``run_sync``, which runs a blocking
    callable on a worker thread from whichever event loop is running.
    """

    context: Context | None = None
    settings: ExecutionSettings = field(default=DEF_EXECUTION_SETTINGS, kw_only=True)
    events: EventSink = field(default=events, kw_only=True)
    _stack: S = field(init=False)
    _closing: bool = field(default=False, init=False)
    _cleanup_errors: list[Exception] = field(factory=list, init=False)
    _acquired: Acquisitions = field(factory=dict, init=False)
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
        Resolves the plan's input values and the context its nodes run under.

        The run's context is derived from the execution's. The execution's own context
        stays as given, so a later run of another plan resolves that plan's defaults
        rather than this run's values.
        """
        if plan.inputs is None:
            given = None if self.context is None else self.context.inputs
            values = resolve_inputs(plan.workflow.input_schemas, given)
            resolved = plan.with_inputs(values)
        else:
            resolved = plan

        if resolved.inputs is None:
            context = self.context
        else:
            given_context = resolve_default(self.context, Context())
            context = given_context.replace(inputs=resolved.inputs)

        return resolved, context

    def _record_cleanup_error(self, func: Func[object], *args: object) -> None:
        """Runs a cleanup callback and saves its failure for the shutdown report."""
        try:
            func(*args)
        except Exception as error:  # noqa: BLE001
            self._cleanup_errors.append(error)

    def queue_callback(self, func: Func[object], *args: object) -> None:
        """
        Registers a synchronous ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(self._record_cleanup_error, func, *args)

    async def to_async[R](self, func: Func[R], *args: object) -> R:
        """
        Runs a blocking sync callable on a worker thread from the running event loop.

        Args:

            func: A synchronous callable to run off the event loop.
            args: Positional arguments forwarded to ``func``.

        Returns:

            The value ``func`` returns.

        """
        self._require_open("run work in")
        return await maybe_async(func, *args, inline=False)

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
                to_async=self.to_async,
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
            seed: The stream fed to the node's open input, if any.

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
