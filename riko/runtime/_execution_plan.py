# vim: sw=4:ts=4:expandtab
"""
Building of a ``Workflow`` into an immutable execution plan.

The build boundary validates the graph, indexes it, and resolves each node's
implementation once, so the returned plan carries the resolution. It performs no
invocation and acquires no resources; the sync/async executions run the plan
without touching the resolver or registry.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from attrs import Factory, define, field

from riko.definitions._workflow import require_module_node
from riko.execution._prepared import PreparedNode, ResolvedModule
from riko.types._collections import freeze_mapping, validator_from_require

from ._resolver import dispatcher

if TYPE_CHECKING:
    from types import MappingProxyType

    from riko.definitions._workflow import Node, Workflow
    from riko.types._collections import FrozenConf
    from riko.types._workflow import GraphIndex, NodeId
    from riko.types.modules import Conf

    from ._resolver import ResolverDispatcher


type PreparedNodes = MappingProxyType[NodeId, PreparedNode]


def _index(self: ExecutionPlan) -> GraphIndex:
    return self.workflow.index


def _require_valid_or_empty(value: Workflow, what: str | None = "value") -> Workflow:
    if not value.is_empty:
        value.validate()

    return value


_valid_workflow = validator_from_require(_require_valid_or_empty)


@define(frozen=True, slots=True)
class ExecutionPlan:
    """
    A prepared workflow: its graph index and resolved nodes.

    Only ``nodes`` is supplied — it carries the once-resolved callables. The graph
    index, including each output's required subgraph, derives from ``workflow``,
    so a plan is consistent however it is constructed. An empty workflow (no nodes,
    edges, or outputs) is the identity plan: running it streams the seeded source
    unchanged.

    Attributes:

        workflow: The ``Workflow`` that was prepared.
        nodes: The resolved nodes, keyed by canonical node id.
        index: The workflow's structural graph index.

    """

    workflow: Workflow = field(validator=_valid_workflow)
    nodes: PreparedNodes = field(converter=freeze_mapping)
    index: GraphIndex = field(init=False, default=Factory(_index, takes_self=True))


def _resolve_module(
    name: str, conf: FrozenConf | Conf, dispatcher: ResolverDispatcher
) -> ResolvedModule:
    dispatcher.validate(name)
    resolve = partial(dispatcher.resolve, name)
    sync_pipe, async_pipe = resolve(), resolve(is_async=True)
    return ResolvedModule(name, conf, sync_pipe=sync_pipe, async_pipe=async_pipe)


def _build_node(node: Node, dispatcher: ResolverDispatcher) -> PreparedNode:
    module_node = require_module_node(node)
    module = _resolve_module(module_node.name, module_node.conf, dispatcher)

    if (embed := module_node.embed) is None:
        resolved_embed = None
    else:
        resolved_embed = _resolve_module(embed["name"], embed["conf"], dispatcher)

    return PreparedNode(module_node, module=module, embed=resolved_embed)


def build_execution_plan(
    workflow: Workflow, dispatcher: ResolverDispatcher = dispatcher
) -> ExecutionPlan:
    """
    Builds an executable snapshot of ``workflow`` with every node resolved once.

    Args:

        workflow: The ``Workflow`` to prepare.
        dispatcher: The pipe resolver supplying node implementations.

    Returns:

        The prepared plan: its graph index and resolved nodes. No node runs and
        no resource is acquired here.

    Raises:

        InvalidPipelineError: If the graph is invalid, a source port fans out to
            more than one edge, a node's positional inputs have gaps, a node
            family has no execution runtime yet, or a node runs a multi-output
            splitter.

        UnsupportedModuleError: If a node's implementation is unresolved.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, Workflow
        >>> from riko.types._workflow import Endpoint
        >>> node = ModuleNode(id="count-1", name="count")
        >>> workflow = Workflow(
        ...     nodes={"count-1": node},
        ...     outputs={"default": Endpoint("count-1", "out")},
        ...     inputs={},
        ...     edges=(),
        ... )
        >>> plan = build_execution_plan(workflow)
        >>> sorted(plan.nodes)
        ['count-1']

    """
    _require_valid_or_empty(workflow)
    workflow.require_executable()
    nodes = {id_: _build_node(node, dispatcher) for id_, node in workflow.nodes.items()}
    return ExecutionPlan(workflow=workflow, nodes=nodes)


__all__ = ["ExecutionPlan", "build_execution_plan"]
