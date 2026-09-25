# vim: sw=4:ts=4:expandtab
"""
Preparation of a canonical workflow into an immutable execution plan.

Preparation validates the graph, indexes it, resolves each node's implementation,
and selects native or adapted execution once so the plan carries the decision. It
performs no invocation and acquires no resources; the sync/async executions run the
returned plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import TYPE_CHECKING

from riko.base.exceptions import InvalidPipelineError, UnsupportedModuleError
from riko.coercion._graph import descendants
from riko.definitions._workflow import ModuleNode
from riko.types._collections import freeze_mapping, require_str

from ._execution._prepared import ExecMode, ExecutionPlan, PreparedNode
from ._graph_index import index_workflow
from ._resolver import pipe_resolver

if TYPE_CHECKING:
    from riko.definitions._workflow import Node, WorkflowSpec
    from riko.types._wrappers import Interface, PipeCallable

    from ._resolver import PipeResolver

_LOOP_OPTION_KEYS = ("emit", "count", "assign", "field")


def prepare_execution(
    spec: WorkflowSpec,
    *,
    is_async: bool = False,
    resolver: PipeResolver = pipe_resolver,
) -> ExecutionPlan:
    """
    Prepares a canonical workflow into an immutable execution plan.

    Args:

        spec: The canonical workflow to prepare.
        is_async: Whether the plan targets asynchronous execution.
        resolver: The pipe resolver supplying node implementations.

    Returns:

        A frozen plan of resolved nodes over the workflow's graph index.

    Raises:

        InvalidPipelineError: If the workflow is structurally invalid or a node
            family has no execution runtime yet.
        UnsupportedModuleError: If a node's implementation is unresolved.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, WorkflowSpec
        >>> from riko.types._workflow import Endpoint
        >>> node = ModuleNode(id="count-1", name="count")
        >>> spec = WorkflowSpec(
        ...     nodes={node.id: node},
        ...     outputs={"default": Endpoint(node.id, "out")},
        ...     inputs={},
        ... )
        >>> prepare_execution(spec).nodes["count-1"].mode.name
        'NATIVE_SYNC'

    """
    spec.validate()
    index = index_workflow(spec)
    prepare = partial(_prepare_node, is_async=is_async, resolver=resolver)
    nodes = {node_id: prepare(node) for node_id, node in spec.nodes.items()}

    items = index.outputs.items()
    _descendants = partial(descendants, graph=index.dependencies)
    required = freeze_mapping(
        {name: _descendants(ref.node) | {ref.node} for name, ref in items}
    )
    return ExecutionPlan(index=index, nodes=freeze_mapping(nodes), required=required)


def _embed_descriptor(conf: Mapping[str, object] | None) -> Mapping[str, object] | None:
    embed = conf.get("embed") if conf else None
    return embed if isinstance(embed, Mapping) and "name" in embed else None


def _prepare_embed(
    descriptor: Mapping[str, object],
    node_id: str,
    *,
    is_async: bool,
    resolver: PipeResolver,
) -> PreparedNode:
    name = require_str(descriptor.get("name"), "loop embed 'name'")
    raw_conf = descriptor.get("conf")
    conf = dict(raw_conf) if isinstance(raw_conf, Mapping) else None

    return PreparedNode(
        id=f"{node_id}::embed",
        name=name,
        family="module",
        pipe=resolver.resolve(name, is_async=is_async),
        mode=ExecMode.NATIVE_ASYNC if is_async else ExecMode.NATIVE_SYNC,
        conf=conf,
        resources={},
    )


def _prepare_node(
    node: Node, *, is_async: bool, resolver: PipeResolver
) -> PreparedNode:
    if not isinstance(node, ModuleNode):
        msg = f"{node.family!r} node execution is not yet supported"
        raise InvalidPipelineError(msg)

    descriptor = _embed_descriptor(node.conf)

    if descriptor is None:
        embed = None
        options = {}
        conf = node.conf
    else:
        loop_conf: Mapping[str, object] = node.conf or {}
        kwargs = {"is_async": is_async, "resolver": resolver}
        embed = _prepare_embed(descriptor, node.id, **kwargs)
        options = {k: loop_conf[k] for k in _LOOP_OPTION_KEYS if k in loop_conf}
        conf = embed.conf

    available = resolver.get_interfaces(node.name)
    pipe, mode = _select_mode(node.name, available, resolver, is_async=is_async)

    return PreparedNode(
        id=node.id,
        name=node.name,
        family=node.family,
        pipe=pipe,
        mode=mode,
        conf=conf,
        resources=node.resources,
        embed=embed,
        options=freeze_mapping(options),
    )


def _select_mode(
    name: str,
    available: frozenset[Interface],
    resolver: PipeResolver,
    *,
    is_async: bool,
) -> tuple[PipeCallable, ExecMode]:
    has_sync = "pipe" in available
    has_async = "async_pipe" in available

    if is_async and has_async:
        result = resolver.resolve(name, is_async=True), ExecMode.NATIVE_ASYNC
    elif is_async and has_sync:
        result = resolver.resolve(name, is_async=False), ExecMode.SYNC_VIA_WORKER
    elif not is_async and has_sync:
        result = resolver.resolve(name, is_async=False), ExecMode.NATIVE_SYNC
    elif not is_async and has_async:
        result = resolver.resolve(name, is_async=True), ExecMode.ASYNC_VIA_PORTAL
    else:
        interface = "async_pipe" if is_async else "pipe"
        raise UnsupportedModuleError(f"{name!r} has no {interface!r}")

    return result


__all__ = ["prepare_execution"]
