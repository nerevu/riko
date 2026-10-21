# vim: sw=4:ts=4:expandtab
"""
Per-item work that synchronous and asynchronous executions run on workers.

A loopable node's bound pipe runs one item at a time on a worker thread or process.
"""

from __future__ import annotations

import pickle  # noqa: S403
from functools import lru_cache, partial
from typing import TYPE_CHECKING, cast

from riko.base._config import SHIPPED_CALL_CACHE_SIZE
from riko.base.exceptions import InvalidPipelineError
from riko.types._enums import Executor

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from riko.definitions._context import Context

    from ._prepared import ExecutionPlan, PreparedNode

__all__ = ["build_item_call", "require_process_safe", "run_item", "run_shipped_item"]


@lru_cache(maxsize=SHIPPED_CALL_CACHE_SIZE)
def _load_call(payload: bytes) -> Callable[[object], Iterable[object]]:
    return pickle.loads(payload)  # noqa: S301


def run_item[T](call: Callable[[T], Iterable[T]], item: T) -> list[T]:
    """
    Runs one item through a bound pipe and collects that item's results.

    Args:

        call: A pipe with its configuration and call options already bound.
        item: The item to run.

    Returns:

        Every result the pipe produced for ``item``.

    Examples:

        >>> from riko.execution._concurrency import run_item
        >>>
        >>> run_item(lambda item: [item, item], {"x": 1})
        [{'x': 1}, {'x': 1}]

    """
    return list(call(item))


def run_shipped_item[T](payload: bytes, item: T) -> list[T]:
    """
    Runs one item through a pickled bound pipe and collects that item's results.

    Args:

        payload: A pickled pipe with its configuration and call options already bound.
        item: The item to run.

    Returns:

        Every result the pipe produced for ``item``.

    Examples:

        >>> import pickle
        >>> from riko.execution._concurrency import run_shipped_item
        >>>
        >>> run_shipped_item(pickle.dumps(list), "ab")
        ['a', 'b']

    """
    call = cast("Callable[[T], Iterable[T]]", _load_call(payload))
    return run_item(call, item)


def build_item_call[T](
    call: Callable[[T], Iterable[T]], executor: Executor
) -> Callable[[T], list[T]]:
    """
    Builds the per-item function a worker pool runs for one mapped node.

    Args:

        call: A pipe with its configuration and call options already bound.
        executor: The executor whose pool runs the items.

    Returns:

        A function that collects one item's results.

    Examples:

        >>> from riko import Executor
        >>> from riko.execution._concurrency import build_item_call
        >>>
        >>> build_item_call(list, Executor.PROCESS)("ab")
        ['a', 'b']

    """
    if executor is Executor.PROCESS:
        func = partial(run_shipped_item, pickle.dumps(call))
    else:
        func = partial(run_item, call)

    return func


def _get_process_unsafe_reason(
    node: PreparedNode, context: Context | None
) -> tuple[str | None, BaseException | None]:
    embed = node.embed
    embed_pipe = None if embed is None else embed.sync_pipe
    reason: str | None = None
    cause: BaseException | None = None

    if node.resources:
        reason = "live resource values cannot cross a process boundary"
    elif embed is not None and embed_pipe is None:
        reason = "its embedded module has no synchronous implementation"
    else:
        try:
            pickle.dumps((node.sync_interface.call, context, embed_pipe))
        except Exception as error:  # noqa: BLE001
            reason, cause = f"it cannot be pickled ({error})", error

    return reason, cause


def require_process_safe(
    plan: ExecutionPlan, output: str, context: Context | None
) -> None:
    """
    Requires every mapped node of a run to be able to cross a process boundary.

    The check runs before any stream is built, so an unshippable node fails the
    run up front rather than after some items have already gone to workers.
    Only the nodes a synchronous run maps are checked: loopable nodes with a
    synchronous implementation and no secondary input stream. Nodes are checked in
    build order, so the first unsafe one is the one reported.

    Args:

        plan: The prepared workflow being run.
        output: The name of the workflow output being run.
        context: The run environment shipped to each worker.

    Raises:

        InvalidPipelineError: If a mapped node declares resources, embeds a
            module with no synchronous implementation, or cannot be pickled.

    Examples:

        >>> from riko import Endpoint, Workflow
        >>> from riko.execution._concurrency import require_process_safe
        >>> from riko.execution._prepared import ExecutionPlan
        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> flow = Workflow(
        ...     nodes=[ModuleNode(id="h", name="hash")],
        ...     outputs={"default": Endpoint("h", "out")},
        ... )
        >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
        >>> require_process_safe(plan, "default", None) is None
        True

    """
    for node_id in plan.index.required[output]:
        node = plan.nodes[node_id]
        reason, cause = (
            _get_process_unsafe_reason(node, context)
            if node.is_sync_mappable
            else (None, None)
        )

        if reason is not None:
            msg = f"node {node_id!r} cannot run on the process executor: {reason}"
            raise InvalidPipelineError(msg) from cause
