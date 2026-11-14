# vim: sw=4:ts=4:expandtab
"""
Per-item work that synchronous and asynchronous executions run on workers.

A mappable node's prepared pipe runs one item at a time on a worker thread or process.
The node's per-item results come back in envelopes that carry their identities.
"""

from __future__ import annotations

import pickle  # noqa: S403
from functools import lru_cache, partial
from typing import TYPE_CHECKING, cast

from riko.base._config import settings as config
from riko.base._exceptions import InvalidPipelineError
from riko.definitions._nodes import CallableNode
from riko.types._enums import Executor
from riko.types._wrappers import RunsItems

from ._provenance import run_tracked_item

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.definitions._context import Context
    from riko.types._enums import IdentityMode
    from riko.types._feed import EnvelopeList, ItemCall, TrackedCall, _ItemEnvelope
    from riko.types._workflow import NodeId, OutputName
    from riko.types._wrappers import Func

    from ._prepared import ExecutionPlan, PreparedNode

__all__ = [
    "build_item_call",
    "build_tracked_call",
    "require_process_safe",
    "run_shipped_item",
]


@lru_cache(maxsize=config.shipped_call_cache_size)
def _load_call(payload: bytes) -> Func[Iterator[object]]:
    return pickle.loads(payload)  # noqa: S301


def run_shipped_item[T](
    payload: bytes,
    node_id: NodeId,
    identity: IdentityMode | None,
    envelope: _ItemEnvelope[T],
) -> EnvelopeList[T]:
    """
    Runs one item through a pickled prepared pipe and collects its resulting envelopes.

    Args:

        payload: The node's pickled per-item call.
        node_id: Id of the node the pipe belongs to.
        identity: The node's identity mode.
        envelope: The input item's envelope.

    Returns:

        Resulting envelopes the pipe produced for the item.

    Examples:

        >>> import pickle
        >>> from riko.execution._concurrency import run_shipped_item
        >>> from riko.types._feed import _ItemEnvelope
        >>>
        >>> envelope = _ItemEnvelope("ab", generation=("s", 0))
        >>> payload = pickle.dumps(iter)
        >>> [r.value for r in run_shipped_item(payload, "n", None, envelope)]
        ['a', 'b']

    """
    call = cast("ItemCall[T]", _load_call(payload))
    return run_tracked_item(call, node_id, identity, envelope)


def build_item_call[T](
    context: Context | None, node: PreparedNode, **extra: object
) -> ItemCall[T]:
    """
    Builds a mappable node's synchronous per-item call with a run's inputs applied.

    ``node`` must be sync native. Each call returns the node's per-item results as a
    synchronous stream. The built call runs under the run's ``context``. Since callable
    nodes don't read ``context``, they get ``None`` instead.

    Args:

        context: The run's context.
        node: The mappable node.

    Kwargs:

        extra: Keyword arguments the execution adds to each call.

    Returns:

        A call that takes an item and returns its results.

    Examples:

        >>> from riko import Workflow
        >>> from riko.execution._concurrency import build_item_call
        >>> from riko.execution._prepared import ExecutionPlan
        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> conf = {"rule": {"transform": "upper"}}
        >>> node = ModuleNode(id="u", name="strtransform", conf=conf)
        >>> flow = Workflow().with_node(node)
        >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
        >>> call = build_item_call(None, plan.nodes["u"])
        >>> list(call({"content": "hi"}))
        [{'content': 'hi', 'strtransform': 'HI'}]

    """
    item_call = node.sync_interface.item_call

    if isinstance(item_call, RunsItems):
        call = partial(item_call.run_item, context, extra)
    else:
        # partial because build_tracked_call pickles for the process pool
        _context = None if isinstance(node.node, CallableNode) else context
        call = partial(item_call, context=_context, **extra)

    return cast("ItemCall[T]", call)


def build_tracked_call[T](
    call: ItemCall[T],
    executor: Executor = Executor.PROCESS,
    *,
    node_id: NodeId,
    identity: IdentityMode | None = None,
) -> TrackedCall[T]:
    """
    Builds the per-item function a worker pool runs for one mapped node.

    The built function runs ``call`` on an item and wraps each result in an envelope
    that keeps or derives the item's identity. The node's identity mode decides which.

    Args:

        call: The node's per-item call with bound configuration and call options.

    Kwargs:

        executor: The executor whose pool runs the items.
        node_id: Id of the node the call belongs to.
        identity: The node's identity mode.

    Returns:

        A function that collects one item's resulting envelopes.

    Examples:

        >>> from riko import Executor
        >>> from riko.execution._concurrency import build_tracked_call
        >>> from riko.types._feed import _ItemEnvelope
        >>>
        >>> envelope = _ItemEnvelope("ab", generation=("s", 0))
        >>> tracked = build_tracked_call(list, node_id="n")
        >>> [result.value for result in tracked(envelope)]
        ['a', 'b']

    """
    if executor is Executor.PROCESS:
        func = partial(run_shipped_item, pickle.dumps(call), node_id, identity)
    else:
        func = partial(run_tracked_item, call, node_id, identity)

    return func


def _get_process_unsafe_reason(
    context: Context | None, node: PreparedNode
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
        extra = {} if embed_pipe is None else {"embed": embed_pipe}
        identity = node.sync_interface.identity

        try:
            args = (context, node)
            call: ItemCall[object] = build_item_call(*args, **extra)
            build_tracked_call(call, node_id=node.node.id, identity=identity)
        except Exception as error:  # noqa: BLE001
            reason, cause = f"it cannot be pickled ({error})", error

    return reason, cause


def require_process_safe(
    plan: ExecutionPlan, output: OutputName, context: Context | None
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

        >>> from riko import Workflow
        >>> from riko.execution._concurrency import require_process_safe
        >>> from riko.execution._prepared import ExecutionPlan
        >>> from riko.ext import ModuleNode
        >>> from riko.runtime._resolver import dispatcher
        >>>
        >>> flow = Workflow().with_node(ModuleNode(id="h", name="hash"))
        >>> plan = ExecutionPlan.from_workflow(flow, dispatcher)
        >>> require_process_safe(plan, "default", None)

    """
    for node_id in plan.index.required[output]:
        node = plan.nodes[node_id]
        reason, cause = (
            _get_process_unsafe_reason(context, node)
            if node.is_sync_mappable
            else (None, None)
        )

        if reason is not None:
            msg = f"node {node_id!r} cannot run on the process executor: {reason}"
            raise InvalidPipelineError(msg) from cause
