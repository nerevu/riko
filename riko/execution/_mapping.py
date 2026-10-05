# vim: sw=4:ts=4:expandtab
"""
Per-item concurrency policy shared by the sync and async executions.

A run's execution settings decide whether each loopable node maps its items
across workers and how many may be in flight. Both executions resolve those
settings here, so the same settings mean the same thing whether a pipeline is
iterated synchronously or asynchronously. These helpers are private to the
runtime and belong to no supported surface.
"""

from __future__ import annotations

import pickle  # noqa: S403
from collections import deque
from queue import SimpleQueue
from typing import TYPE_CHECKING, NamedTuple, Self

from attrs import define, field

from riko.base._config import settings as config
from riko.base.exceptions import InvalidPipelineError
from riko.types._enums import Executor
from riko.types._guards import is_streamlike

from ._pools import get_worker_cnt
from ._prepared import ExecMode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping
    from multiprocessing.pool import ApplyResult
    from types import TracebackType

    from riko.definitions._execution import ExecutionSettings
    from riko.runtime._execution_plan import ExecutionPlan

    from ._pools import AnyPool, PoolHandle
    from ._prepared import PreparedNode
    from .context import Context

__all__ = [
    "AsyncPolicy",
    "SyncPolicy",
    "is_mappable",
    "require_process_safe",
    "resolve_async_policy",
    "resolve_sync_policy",
    "run_item",
]


class SyncPolicy(NamedTuple):
    """
    How a synchronous run maps a loopable node's items.

    Attributes:

        executor: The effective executor; never ``AUTO``.
        workers: The pool size, or ``None`` to run items sequentially without
            a pool.

    """

    executor: Executor
    workers: int | None


class AsyncPolicy(NamedTuple):
    """
    How an asynchronous run maps a loopable node's items.

    Attributes:

        limit: The per-run ceiling on items in flight, or ``None`` to run items
            sequentially.
        inline: Whether a synchronous pipe runs on the event-loop thread
            instead of a worker thread.

    """

    limit: int | None
    inline: bool


def resolve_sync_policy(settings: ExecutionSettings) -> SyncPolicy:
    """
    Decides where a synchronous run's per-item work runs and how wide it fans out.

    ``AUTO`` maps across threads only when ``concurrency`` asks for more than one
    item in flight; ``INLINE`` never opens a pool. An explicit thread or process
    executor without a ``concurrency`` gets a pool sized from the machine's
    cores rather than one worker or an unbounded count.

    Args:

        settings: The run's execution settings.

    Returns:

        The effective executor and pool size.

    Examples:

        >>> from riko.definitions._execution import ExecutionSettings
        >>> from riko.execution._mapping import resolve_sync_policy
        >>>
        >>> resolve_sync_policy(ExecutionSettings())
        SyncPolicy(executor=<Executor.INLINE: 'inline'>, workers=None)
        >>> resolve_sync_policy(ExecutionSettings(concurrency=4))
        SyncPolicy(executor=<Executor.THREAD: 'thread'>, workers=4)

    """
    executor, concurrency = settings.executor, settings.concurrency

    if executor is Executor.AUTO and concurrency is not None and concurrency > 1:
        policy = SyncPolicy(Executor.THREAD, concurrency)
    elif executor in {Executor.AUTO, Executor.INLINE}:
        policy = SyncPolicy(Executor.INLINE, None)
    elif concurrency is None:
        workers = get_worker_cnt(0, threads=executor is Executor.THREAD)
        policy = SyncPolicy(executor, workers)
    else:
        policy = SyncPolicy(executor, concurrency)

    return policy


def resolve_async_policy(settings: ExecutionSettings) -> AsyncPolicy:
    """
    Decides how many items an asynchronous run keeps in flight per run.

    ``AUTO`` stays sequential unless ``concurrency`` is set. An explicit
    ``INLINE`` or ``THREAD`` executor without a ``concurrency`` uses the
    project's default connection ceiling; ``INLINE`` also keeps synchronous
    pipes on the event-loop thread.

    Args:

        settings: The run's execution settings.

    Returns:

        The in-flight ceiling and whether synchronous pipes run inline.

    Raises:

        InvalidPipelineError: If the settings name the process executor, which
            asynchronous iteration cannot use.

    Examples:

        >>> from riko.definitions._execution import ExecutionSettings
        >>> from riko.execution._mapping import resolve_async_policy
        >>>
        >>> resolve_async_policy(ExecutionSettings(concurrency=4))
        AsyncPolicy(limit=4, inline=False)
        >>> resolve_async_policy(ExecutionSettings(executor="process"))
        Traceback (most recent call last):
        riko.base.exceptions.InvalidPipelineError: ...requires synchronous execution

    """
    executor, concurrency = settings.executor, settings.concurrency

    if executor is Executor.PROCESS:
        msg = "the process executor requires synchronous execution"
        raise InvalidPipelineError(msg)
    elif executor is Executor.AUTO:
        policy = AsyncPolicy(concurrency, False)
    else:
        limit = config.connection_count if concurrency is None else concurrency
        policy = AsyncPolicy(limit, executor is Executor.INLINE)

    return policy


def run_item[T](call: Callable[[T], Iterable[T]], item: T) -> list[T]:
    """
    Runs one item through a bound pipe and collects that item's results.

    It lives at module scope so a process pool can ship it to a worker.

    Args:

        call: A pipe with its configuration and call options already bound.
        item: The item to run.

    Returns:

        Every result the pipe produced for ``item``.

    Examples:

        >>> from riko.execution._mapping import run_item
        >>>
        >>> run_item(lambda item: [item, item], {"x": 1})
        [{'x': 1}, {'x': 1}]

    """
    return list(call(item))


def is_mappable(node: PreparedNode, extra: Mapping[str, object]) -> bool:
    """
    Reports whether a node's items may run one at a time across workers.

    Only a loopable node qualifies, and only when none of its secondary inputs is
    a stream: a stream-valued input is shared by the whole call and cannot be
    split per item. Resource views, option values, and embed callables are fine.

    Args:

        node: The prepared node about to run.
        extra: The secondary inputs and call arguments bound for the node.

    Returns:

        Whether the node's items may be mapped.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, Workflow
        >>> from riko.execution._mapping import is_mappable
        >>> from riko.runtime._execution_plan import build_execution_plan
        >>> from riko.types._workflow import Endpoint
        >>>
        >>> workflow = Workflow(
        ...     nodes={"h": ModuleNode(id="h", name="hash")},
        ...     outputs={"default": Endpoint("h", "out")},
        ... )
        >>> node = build_execution_plan(workflow).nodes["h"]
        >>> is_mappable(node, {"emit": True}), is_mappable(node, {"other": iter([])})
        (True, False)

    """
    values = extra.values()
    nested = (v for value in values if isinstance(value, list) for v in value)
    has_streams = any(map(is_streamlike, values)) or any(map(is_streamlike, nested))
    return node.loopable and not has_streams


def _process_unsafe_reason(
    node: PreparedNode, context: Context | None
) -> tuple[str | None, BaseException | None]:
    embed = node.embed
    pipe = node.select(is_async=False).pipe
    embed_pipe = None if embed is None else embed.select(is_async=False)
    conf, options = node.embed_or_self_conf, dict(node.options)
    reason: str | None = None
    cause: BaseException | None = None

    if node.resources:
        reason = "live resource values cannot cross a process boundary"
    elif embed_pipe is not None and embed_pipe.mode is ExecMode.ADAPTER:
        reason = "its embedded module has no synchronous implementation"
    else:
        shipped = None if embed_pipe is None else embed_pipe.pipe

        try:
            pickle.dumps((pipe, conf, options, context, shipped))
        except (pickle.PicklingError, TypeError, AttributeError) as error:
            reason, cause = f"it cannot be pickled ({error})", error

    return reason, cause


def require_process_safe(
    plan: ExecutionPlan, required: Iterable[str], context: Context | None
) -> None:
    """
    Requires every mapped node of a run to be able to cross a process boundary.

    The check runs before any stream is built, so an unshippable node fails the
    run up front rather than after some items have already gone to workers.
    Only loopable nodes with a synchronous implementation are mapped, so only
    those are checked.

    Args:

        plan: The prepared workflow being run.
        required: The node ids the selected output runs.
        context: The execution context shipped to each worker.

    Raises:

        InvalidPipelineError: If a mapped node declares resources, embeds a
            module with no synchronous implementation, or cannot be pickled.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, Workflow
        >>> from riko.execution._mapping import require_process_safe
        >>> from riko.runtime._execution_plan import build_execution_plan
        >>> from riko.types._workflow import Endpoint
        >>>
        >>> workflow = Workflow(
        ...     nodes={"h": ModuleNode(id="h", name="hash")},
        ...     outputs={"default": Endpoint("h", "out")},
        ... )
        >>> plan = build_execution_plan(workflow)
        >>> require_process_safe(plan, {"h"}, None) is None
        True

    """
    for node_id in required:
        node = plan.nodes[node_id]
        mapped = node.loopable and node.select(is_async=False).mode is ExecMode.NATIVE

        reason, cause = (
            _process_unsafe_reason(node, context) if mapped else (None, None)
        )

        if reason is not None:
            msg = f"node {node_id!r} cannot run on the process executor: {reason}"
            raise InvalidPipelineError(msg) from cause


@define(frozen=True, slots=True)
class _Failure:
    """Carries a worker's error back to the consuming thread."""

    error: BaseException


def _map_ordered[T, R](
    pool: AnyPool, func: Callable[[T], R], source: Iterable[T], window: int
) -> Iterator[R]:
    """Unlike ``Pool.imap``, maps in source order and pulls at most ``window`` ahead."""
    pending: deque[ApplyResult[R]] = deque()

    for item in source:
        pending.append(pool.apply_async(func, (item,)))

        if len(pending) >= window:
            yield pending.popleft().get()

    while pending:
        yield pending.popleft().get()


def _map_unordered[T, R](
    pool: AnyPool, func: Callable[[T], R], source: Iterable[T], window: int
) -> Iterator[R]:
    """Unlike ``imap``, maps in completion order and pulls at most ``window`` ahead."""
    done: SimpleQueue[R | _Failure] = SimpleQueue()
    pending = 0

    def take() -> R:
        if isinstance(value := done.get(), _Failure):
            raise value.error

        return value

    def submit(item: T) -> None:
        pool.apply_async(
            func,
            (item,),
            callback=done.put,
            error_callback=lambda error: done.put(_Failure(error)),
        )

    for item in source:
        submit(item)
        pending += 1

        if pending >= window:
            pending -= 1
            yield take()

    for _ in range(pending):
        yield take()


@define(eq=False)
class _PoolLifetime:
    """
    Owns an execution's shared worker pool and decides how it is released.

    The pool waits out its pending work only when every mapped stream ran to
    exhaustion and no error is propagating; otherwise in-flight and read-ahead
    work is stopped at once, so an early-closed or failed run never waits on it.
    """

    handle: PoolHandle
    window: int
    abandoned: bool = field(default=False, init=False)
    _active: int = field(default=0, init=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None and not self.abandoned and not self._active:
            self.handle.close()
        else:
            self.handle.terminate()

    def map_items[T](
        self, func: Callable[[T], list[T]], source: Iterable[T], *, ordered: bool
    ) -> Iterator[T]:
        """
        Maps ``func`` over ``source`` on the pool and flattens each item's results.

        The source is pulled by the consumer, never ahead of it by more than the
        pool's width, so mapped nodes can share one pool and chain freely.

        Args:

            func: Collects one item's results.
            source: The items to map.
            ordered: Whether results keep source order.

        Yields:

            Each result item, in source order when ``ordered`` and in
            completion order otherwise.

        Raises:

            RuntimeError: If the pool was already released.

        """
        if (pool := self.handle.pool) is None:
            raise RuntimeError("Cannot reuse a closed worker pool")

        mapper = _map_ordered if ordered else _map_unordered
        self._active += 1

        try:
            for results in mapper(pool, func, source, self.window):
                yield from results
        except GeneratorExit:
            self.abandoned = True
            raise
        else:
            self._active -= 1
