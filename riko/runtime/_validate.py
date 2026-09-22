# vim: sw=4:ts=4:expandtab
"""
Strict structural validation of a canonical Workflow v2 spec.

``validate_workflow`` checks a normalized ``WorkflowSpec`` against the closed-schema
graph rules and raises ``InvalidPipelineError`` on the first violation. It answers "is
this a valid graph?", not "can this run here?".

Examples:

    Basic usage::

        >>> from riko.runtime._normalize import normalize_workflow
        >>> from riko.runtime._validate import validate_workflow
        >>>
        >>> spec = normalize_workflow(
        ...     {
        ...         "nodes": [{"name": "fetch"}, {"name": "filter"}],
        ...         "edges": [
        ...             {"source": {"node": "fetch-1"}, "target": {"node": "filter-1"}}
        ...         ],
        ...     }
        ... )
        >>> validate_workflow(spec) is None
        True

"""

from __future__ import annotations

from collections import Counter
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING

from riko.base.exceptions import InvalidPipelineError
from riko.definitions._workflow import SubscribeNode
from riko.types._workflow import WORKFLOW_VERSION

if TYPE_CHECKING:
    from riko.definitions._workflow import Edge, Node, WorkflowSpec
    from riko.types._workflow import Endpoint


def _get_port(edge: Edge) -> tuple[str, str]:
    return edge.target.node, edge.target.port


def _check_version(spec: WorkflowSpec) -> None:
    """Rejects a spec whose version is not the supported canonical version."""
    if spec.version != WORKFLOW_VERSION:
        raise InvalidPipelineError(f"unsupported workflow version: {spec.version!r}")


def _check_nonempty(spec: WorkflowSpec) -> None:
    """Rejects a spec that declares no executable node."""
    if not spec.nodes:
        raise InvalidPipelineError("workflow has no nodes")


def _check_node_ids(spec: WorkflowSpec) -> None:
    """Rejects a node whose id disagrees with the key it is stored under."""
    if mismatched := [key for key, node in spec.nodes.items() if key != node.id]:
        raise InvalidPipelineError(f"node id does not match its key: {mismatched}")


def _endpoints(spec: WorkflowSpec) -> list[Endpoint]:
    """Collects every endpoint referenced by an edge or a named output."""
    edge_ends = chain.from_iterable((edge.source, edge.target) for edge in spec.edges)
    return list(chain(edge_ends, spec.outputs.values()))


def _check_references(spec: WorkflowSpec) -> None:
    """Rejects an edge or output that references a node not in the graph."""
    if missing := {end.node for end in _endpoints(spec) if end.node not in spec.nodes}:
        raise InvalidPipelineError(f"references to missing node(s): {sorted(missing)}")


def _check_fanin(spec: WorkflowSpec, family: str = "stream") -> None:
    """Rejects more than one stream edge feeding a single target port."""
    ports = Counter(_get_port(edge) for edge in spec.edges if edge.family == family)

    if crowded := sorted({port for port, count in ports.items() if count > 1}):
        raise InvalidPipelineError(f"multiple stream edges into port(s): {crowded}")


def _edge_target_mismatch(edge: Edge, **nodes: Node) -> str | None:
    """Detects a publish/subscribe mismatch between an edge and its target node."""
    node = nodes.get(edge.target.node)

    if (edge.family == "publish") != isinstance(node, SubscribeNode):
        return edge.target.node


def _check_edge_families(spec: WorkflowSpec) -> None:
    """Rejects a publish edge to a non-subscribe node or a stream edge to one."""
    mismatched = map(partial(_edge_target_mismatch, **spec.nodes), spec.edges)

    if wrong := sorted(filter(None, mismatched)):
        raise InvalidPipelineError(f"edge family disagrees with target node: {wrong}")


def _check_resources(spec: WorkflowSpec) -> None:
    """Rejects a node resource binding to a name absent from declared resources."""
    used = chain.from_iterable(node.resources.values() for node in spec.nodes.values())

    if undeclared := sorted(set(used).difference(spec.resources)):
        raise InvalidPipelineError(f"unresolved resource reference(s): {undeclared}")


def _check_outputs(spec: WorkflowSpec) -> None:
    """Rejects a non-empty graph that exposes no named output."""
    if spec.nodes and not spec.outputs:
        raise InvalidPipelineError("workflow exposes no output; declare 'outputs'")


def validate_workflow(spec: WorkflowSpec) -> None:
    """
    Validates a canonical Workflow v2 spec, raising on the first structural violation.

    The checks are graph-structural and determinable from the spec alone: the workflow
    version, a non-empty node set, node-id/key agreement, edge and output references
    resolving to real nodes, at most one stream edge per target port, publish/subscribe
    edge-family coherence, resource references resolving to declared resources, and a
    non-empty graph exposing at least one output.

    Args:

        spec: The canonical spec, typically produced by ``normalize_workflow``.

    Raises:

        InvalidPipelineError: When the spec violates a structural rule.

    Examples:

        >>> from riko.runtime._normalize import normalize_workflow
        >>> spec = normalize_workflow({"nodes": [{"id": "a", "name": "fetch"}]})
        >>> validate_workflow(spec) is None
        True

    """
    _check_version(spec)
    _check_nonempty(spec)
    _check_node_ids(spec)
    _check_references(spec)
    _check_fanin(spec)
    _check_edge_families(spec)
    _check_resources(spec)
    _check_outputs(spec)


__all__ = ["validate_workflow"]
