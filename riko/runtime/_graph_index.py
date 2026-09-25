# vim: sw=4:ts=4:expandtab
"""
Canonical Workflow v2 graph indexing.

Builds the shared immutable graph index from a validated ``WorkflowSpec``. The
assembly is factored into ``build_graph_index`` so the v1 compiler and the v2
workflow feed one implementation rather than deriving separate topologies.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from riko.coercion._graph import topological_sort
from riko.types._collections import freeze_mapping
from riko.types._compiler import GraphEdge, GraphIndex, OutputRef

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.definitions._workflow import WorkflowSpec


def build_graph_index(
    adjacency: Mapping[str, set[str]],
    edges: tuple[GraphEdge, ...],
    outputs: Mapping[str, OutputRef],
) -> GraphIndex:
    """
    Assembles a graph index from adjacency, edges, and named outputs.

    Args:

        adjacency: Each node mapped to the nodes that run after it.
        edges: The port-level connections, in listing order.
        outputs: The named outputs, each an output reference.

    Returns:

        A frozen ``GraphIndex`` describing the topology.

    """
    order = tuple(topological_sort(adjacency, strict=True))
    dependents = {node: frozenset(succ) for node, succ in adjacency.items()}
    _dependencies: dict[str, set[str]] = {node: set() for node in adjacency}

    for node, succ in adjacency.items():
        for successor in succ:
            _dependencies[successor].add(node)

    dependencies = {node: frozenset(deps) for node, deps in _dependencies.items()}
    roots = tuple(node for node in order if not dependencies.get(node))
    leaves = tuple(node for node in order if not dependents.get(node))
    _incoming: dict[str, list[GraphEdge]] = defaultdict(list)
    _outgoing: dict[str, list[GraphEdge]] = defaultdict(list)

    for edge in edges:
        _outgoing[edge.source].append(edge)
        _incoming[edge.target].append(edge)

    incoming = {node: tuple(group) for node, group in _incoming.items()}
    outgoing = {node: tuple(group) for node, group in _outgoing.items()}

    return GraphIndex(
        edges=edges,
        incoming=freeze_mapping(incoming),
        outgoing=freeze_mapping(outgoing),
        dependencies=freeze_mapping(dependencies),
        dependents=freeze_mapping(dependents),
        order=order,
        roots=roots,
        leaves=leaves,
        outputs=freeze_mapping(outputs),
    )


def index_workflow(spec: WorkflowSpec) -> GraphIndex:
    """
    Interprets a canonical workflow's nodes and edges into one graph index.

    Every declared node is included and disconnected nodes retained, and the
    explicit named outputs are preserved. Assumes a validated ``WorkflowSpec``.

    Args:

        spec: The canonical workflow to index.

    Returns:

        A frozen ``GraphIndex`` describing the workflow's topology.

    Examples:

        >>> from riko.definitions._workflow import ModuleNode, WorkflowSpec
        >>> from riko.types._workflow import Endpoint
        >>> node = ModuleNode(id="fetch-1", name="fetch")
        >>> spec = WorkflowSpec(
        ...     nodes={node.id: node},
        ...     outputs={"default": Endpoint(node.id, "out")},
        ...     inputs={},
        ... )
        >>> index_workflow(spec).order
        ('fetch-1',)

    """
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in spec.nodes}

    for edge in spec.edges:
        adjacency[edge.source.node].add(edge.target.node)

    edges = tuple(
        GraphEdge(
            source=edge.source.node,
            target=edge.target.node,
            source_port=edge.source.port,
            target_port=edge.target.port,
        )
        for edge in spec.edges
    )
    items = spec.outputs.items()
    outputs = {name: OutputRef(node=ep.node, port=ep.port) for name, ep in items}

    return build_graph_index(adjacency, edges, outputs)


__all__ = ["build_graph_index", "index_workflow"]
