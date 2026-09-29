# vim: sw=4:ts=4:expandtab
"""
Building of a canonical workflow into an immutable execution plan.

The build boundary validates the graph, indexes it, and resolves each node's
implementation once, so the returned plan carries the resolution. It performs no
invocation and acquires no resources; the sync/async executions run the plan
without touching the resolver or registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import TYPE_CHECKING, cast

from attrs import Factory, define, field

from riko.coercion._graph import descendants
from riko.execution._prepared import PreparedNode
from riko.types._collections import freeze_mapping

from ._graph_index import index_workflow
from ._resolver import dispatcher

if TYPE_CHECKING:
    from types import MappingProxyType

    from riko.definitions._workflow import Node, WorkflowSpec
    from riko.types._compiler import GraphIndex
    from riko.types._workflow import NodeId
    from riko.types._wrappers import AsyncModuleWrapper, SyncModuleWrapper
    from riko.types.modules import Embed

    from ._resolver import ResolverDispatcher


type PreparedNodes = MappingProxyType[NodeId, PreparedNode]
type RequiredNodes = MappingProxyType[str, frozenset[NodeId]]
type ResolvedPipes = tuple[SyncModuleWrapper | None, AsyncModuleWrapper | None]


def _index(self: ExecutionPlan) -> GraphIndex:
    return index_workflow(self.spec)


def _required(self: ExecutionPlan) -> RequiredNodes:
    _descendants = partial(descendants, graph=self.index.dependencies)
    items = self.index.outputs.items()
    required = {name: _descendants(ref.node) | {ref.node} for name, ref in items}
    return freeze_mapping(required)


required = Factory(_required, takes_self=True)


@define(frozen=True, slots=True)
class ExecutionPlan:
    """
    A prepared workflow: its graph index, resolved nodes, and per-output subgraphs.

    Only ``nodes`` is supplied — it carries the once-resolved callables. The graph
    index and per-output subgraphs derive from ``spec``, so a plan is consistent
    however it is constructed.

    Attributes:

        spec: The canonical workflow that was prepared.
        nodes: The resolved nodes, keyed by canonical node id.
        index: The structural graph index shared with the compiler.
        required: For each named output, the node ids its subgraph must run.

    """

    spec: WorkflowSpec = field(validator=lambda inst, field, value: value.validate())
    nodes: PreparedNodes = field(converter=freeze_mapping)
    index: GraphIndex = field(init=False, default=Factory(_index, takes_self=True))
    required: RequiredNodes = field(init=False, default=required)


def _resolve_pipes(name: str, dispatcher: ResolverDispatcher) -> ResolvedPipes:
    dispatcher.validate(name)
    resolve = partial(dispatcher.resolve_if_capable, name)
    return resolve(), resolve(is_async=True)


def _build_embed(
    base: PreparedNode, dispatcher: ResolverDispatcher
) -> PreparedNode | None:
    ref = base.conf.get("embed")

    if isinstance(ref, Mapping) and "name" in ref:
        embed = cast("Embed", ref)
        sync_pipe, async_pipe = _resolve_pipes(embed["name"], dispatcher)
        result = PreparedNode(
            node=base.node,
            id=f"{base.id}::embed",
            name=embed["name"],
            conf=embed["conf"],
            options={},
            resources={},
            sync_pipe=sync_pipe,
            async_pipe=async_pipe,
        )
    else:
        result = None

    return result


def _build_node(node: Node, dispatcher: ResolverDispatcher) -> PreparedNode:
    base = PreparedNode(node)
    sync_pipe, async_pipe = _resolve_pipes(base.name, dispatcher)
    embed = _build_embed(base, dispatcher)
    return PreparedNode(node, sync_pipe=sync_pipe, async_pipe=async_pipe, embed=embed)


def build_execution_plan(
    spec: WorkflowSpec, dispatcher: ResolverDispatcher = dispatcher
) -> ExecutionPlan:
    """
    Builds an executable snapshot of ``spec`` with every node resolved once.

    Args:

        spec: The canonical workflow to prepare.
        dispatcher: The pipe resolver supplying node implementations.

    Returns:

        The prepared plan: its graph index, resolved nodes, and per-output
        subgraphs. No node runs and no resource is acquired here.

    Raises:

        InvalidPipelineError: If the graph is invalid, a node family has no
            execution runtime yet, or a node runs a multi-output splitter.
        UnsupportedModuleError: If a node's implementation is unresolved.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, WorkflowSpec
        >>> from riko.types._workflow import Endpoint
        >>> node = ModuleNode(id="count-1", name="count")
        >>> spec = WorkflowSpec(
        ...     nodes={"count-1": node},
        ...     outputs={"default": Endpoint("count-1", "out")},
        ...     inputs={},
        ...     edges=(),
        ... )
        >>> plan = build_execution_plan(spec)
        >>> sorted(plan.nodes)
        ['count-1']

    """
    spec.validate()
    nodes = {id_: _build_node(node, dispatcher) for id_, node in spec.nodes.items()}
    return ExecutionPlan(spec=spec, nodes=nodes)


__all__ = ["ExecutionPlan", "build_execution_plan"]
