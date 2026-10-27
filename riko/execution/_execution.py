# vim: sw=4:ts=4:expandtab
"""
Shared state and plan checks for the private sync/async executions.

A prepared workflow (an execution plan) is a reusable structural snapshot; running
it creates a one-shot sync or async execution. Each owns the exit stack and sync/async
bridge that scope a run's acquired resources and adapted work. These
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
from contextlib import AsyncExitStack, ExitStack
from typing import TYPE_CHECKING, Any, Never, cast, overload

from attrs import Factory, define, field

from riko.bado._backend import asyncify
from riko.base._config import FOREVER_ITEM
from riko.base._exceptions import InvalidPipelineError, PipelineStateError
from riko.definitions._settings import DEF_EXECUTION_SETTINGS, ExecutionSettings
from riko.types._frozendict import FrozenDict
from riko.types._workflow import parse_port
from riko.types._wrappers import ModuleWrapper

from ._prepared import require_default_output_port
from ._resource_view import ResourceView

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from anyio.from_thread import BlockingPortal

    from riko.definitions._context import Context
    from riko.definitions._resource_definition import Resource
    from riko.types._events import EventSink
    from riko.types._workflow import GraphEdge


type SyncExecSteps[T] = dict[str, Iterator[T]]
type AsyncExecSteps[T] = dict[str, AsyncIterator[T]]
type ExtraObjects[T] = ResourceView | ModuleWrapper
type ExtraStreams[T] = (
    AsyncIterable[T] | list[AsyncIterable[T]] | Iterator[T] | Iterable[Iterator[T]]
)
type ExtraValues[T] = ExtraObjects[T] | ExtraStreams[T]
type ExtraInput[T] = Mapping[str, ExtraValues[T]]
type ExtraOutput[T] = dict[str, ExtraValues[T]]
type Acquisition[T] = _Acquired[T] | _FailedAcquisition
type Acquisitions = dict[Resource[Any], Acquisition[Any]]

DEFAULT_SEED: tuple[FrozenDict[str, bool], ...] = (FrozenDict(FOREVER_ITEM),)


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


def _require_seed[S](seed: S | None, output: str) -> S:
    """Requires the seed an identity plan streams as its default output."""
    if output != "default":
        raise InvalidPipelineError(f"workflow has no workflow output {output!r}")
    elif seed is None:
        msg = "workflow has no nodes; an empty workflow requires a seed"
        raise InvalidPipelineError(msg)

    return seed


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


def _event_sink(self: _BaseExecution) -> EventSink:
    sink = self.settings.event_sink
    return _NULL_EVENT_SINK if sink is None else sink


events = Factory(_event_sink, takes_self=True)


@define(eq=False)
class _BaseExecution[S: (ExitStack, AsyncExitStack)]:
    """
    Shares the state and checks both executions run without awaiting.

    That covers the context and settings, the closed-state guard, synchronous
    exit-stack entry, cleanup-error reporting, the resolved-resource cache,
    resource-binding checks, and input wiring.
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

    def callback(self, func: Callable, *args: object) -> None:
        """
        Registers a synchronous ``func`` to run during exit-stack unwind.

        Args:

            func: A cleanup callable invoked with ``args`` on shutdown.
            args: Positional arguments forwarded to ``func``.

        """
        self._require_open("add a callback to")
        self._stack.callback(self._record_cleanup_error, func, *args)

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

    def _require_bindings(self, binding: Mapping[str, str]) -> dict[str, Resource[Any]]:
        """Requires the context to provide every resource a node binds, by slot."""
        context = self.context
        available = {} if context is None else context.resources

        if missing := sorted(set(binding.values()).difference(available)):
            names = ", ".join(repr(name) for name in missing)
            msg = f"resource(s) {names} not provided by the context"
            raise InvalidPipelineError(msg)

        return {slot: available[name] for slot, name in binding.items()}

    def _resolve_node_inputs[I, V: (Iterator[Any], AsyncIterator[Any])](
        self,
        incoming: tuple[GraphEdge, ...],
        steps: Mapping[str, V],
        seed: I | None,
        *,
        as_stream: Callable[[I | Iterable[Any]], V],
    ) -> tuple[V, ExtraOutput]:
        """
        Wires a node's upstream streams onto its input ports.

        The default input port takes its upstream stream, or else the seed. Positional
        ``in:<n>`` ports arrive in order as ``others`` and named ``in:<name>`` ports
        under their own name. When the default input port gets neither, the primary
        input stream is empty if positional ports are wired and holds the default seed
        items otherwise.

        Args:

            incoming: The stream edges that target the node.
            steps: The streams already built for upstream nodes.
            seed: The items fed to the node's open input, if any.
            as_stream: Turns the seed into the execution's stream kind.

        Returns:

            The node's primary input stream and its secondary input streams.

        """
        source: V | None = None if seed is None else as_stream(seed)
        indexed: list[tuple[int, V]] = []
        extra: ExtraOutput = {}

        for edge in incoming:
            require_default_output_port(edge.source_port, f"edge from {edge.source!r}")
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
            extra["others"] = cast("ExtraStreams", [stream for _, stream in ordered])

        if source is None:
            seed_items: Iterable[Any] = () if indexed else DEFAULT_SEED
            source = as_stream(seed_items)

        return source, extra

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
