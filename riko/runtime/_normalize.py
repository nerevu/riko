# vim: sw=4:ts=4:expandtab
"""
The single shorthand normalization boundary for ``Workflow`` graphs.

``normalize_workflow`` turns a flexible ``WorkflowLike`` into one strict ``Workflow``
so no other subsystem has to reinterpret shorthand. It
is the structural, contract-free pass. Malformed structure raises
``InvalidPipelineError``.

Examples:

    Basic usage::

        >>> from riko.runtime._normalize import normalize_workflow
        >>>
        >>> workflow = normalize_workflow({"nodes": [{"name": "fetch"}]})
        >>> workflow.validate()
        >>> list(workflow.nodes)
        ['fetch-1']
        >>> workflow.outputs["default"]
        Endpoint(node='fetch-1', port='out')

"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from itertools import count, starmap
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, get_args

from attrs import asdict

from riko.base._config import INPUT_PORT, OTHER_PORT, OUTPUT_PORT
from riko.base.exceptions import InvalidPipelineError
from riko.coercion._sequences import require_sequence
from riko.definitions._workflow import (
    ActionNode,
    CacheNode,
    ModuleNode,
    Node,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    Workflow,
    WriteNode,
)
from riko.types._collections import (
    FrozenJSON,
    field_names,
    freeze_mapping,
    require_str,
    require_strlike,
)
from riko.types._guards import is_mapping, require_mapping
from riko.types._workflow import (
    WORKFLOW_VERSION,
    Edge,
    EdgeFamily,
    Endpoint,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
    parse_port,
)

if TYPE_CHECKING:
    from riko.definitions._workflow import WorkflowLike
    from riko.types._workflow import JSONSchema


_EDGE_ALIASES = frozenset({"src", "tgt", "from", "to"})


def _reject_unknown(present: Mapping[str, object], cls: type, *extra: str) -> None:
    """Rejects any shorthand key outside the closed set for ``what``."""
    if unknown := sorted(set(present).difference([*field_names(cls), *extra])):
        raise InvalidPipelineError(f"unknown {cls.__name__} field(s): {unknown}")


def _get_legacy_index(port: str, prefix: str, default: int) -> int:
    """Reads the trailing number off a legacy ``_OTHER``/``_OUTPUT`` port suffix."""
    suffix = port.removeprefix(prefix)
    return int(suffix) if suffix.isdigit() else default


def _is_legacy_port(port: str, prefix: str) -> bool:
    """Confirms a legacy port suffix is empty or a bare series number."""
    suffix = port.removeprefix(prefix)
    return not suffix or suffix.isdigit()


def _normalize_port(port: str, direction: str) -> str:
    """Maps a legacy or bare named port to the canonical grammar for ``direction``."""
    if not port or port in {"in", "out"}:
        result = port
    elif port == INPUT_PORT:
        result = "in"
    elif port == OUTPUT_PORT:
        result = "out"
    elif _is_legacy_port(port, OTHER_PORT):
        result = f"in:{_get_legacy_index(port, OTHER_PORT, 1)}"
    elif _is_legacy_port(port, OUTPUT_PORT):
        index = _get_legacy_index(port, OUTPUT_PORT, 1) - 1
        result = "out" if index < 1 else f"out:{index}"
    elif port.isidentifier():
        result = f"{direction}:{port}"
    else:
        result = port

    return result


def _validate_port(port: str) -> None:
    """Rejects an empty port or a malformed ``in``/``out`` directional form."""
    try:
        parse_port(port)
    except ValueError as e:
        raise InvalidPipelineError(f"invalid port: {port!r}") from e


_NODE_BUILDERS: Mapping[str, type[Node]] = {
    "module": ModuleNode,
    "read": ReadNode,
    "write": WriteNode,
    "action": ActionNode,
    "cache": CacheNode,
    "subscribe": SubscribeNode,
}


def _build_node(family: object | None = "module", **fields: Any) -> Node:
    """Dispatches a ``RawNode`` to its closed node family builder."""
    resolved = str(fields.pop("type", family))

    if "format" in fields and "fmt" in fields:
        raise InvalidPipelineError("use 'fmt' or 'format', not both")
    elif "format" in fields:
        fields["fmt"] = fields.pop("format")

    if (builder := _NODE_BUILDERS.get(resolved)) is None:
        raise InvalidPipelineError(f"unknown node family: {resolved!r}")

    _reject_unknown(fields, builder)
    return builder(**fields)


def _normalize_node(*raw_nodes: object) -> Iterator[RawNode]:
    """Pairs list-authored nodes with explicit or generated ``<name>-<occurrence>``."""
    counts: dict[str, int] = {}

    for raw_node in raw_nodes:
        node: dict[str, Any] = dict(require_mapping(raw_node, "node"))
        name = node.get("name")

        if (node_id := node.pop("id", None)) is None:
            name = require_str(name, "node 'name'")
            counts[name] = counts.get(name, 0) + 1
            node_id = f"{name}-{counts[name]}"

        yield RawNode(id=str(node_id), **node)


def _keyed_node(key: object, raw_node: object) -> dict[str, Any]:
    """Applies the authoritative mapping key and rejects a conflicting inner ``id``."""
    node = dict(require_mapping(raw_node, "node"))
    inner = node.get("id")

    if inner is not None and str(inner) != str(key):
        raise InvalidPipelineError(f"node id {inner!r} conflicts with its key {key!r}")

    node["id"] = key
    return node


def _normalize_nodes(raw_nodes: object) -> dict[str, Node]:
    """Normalizes list- or mapping-authored nodes into canonical id-keyed nodes."""
    if isinstance(raw_nodes, Mapping):
        _nodes = starmap(_keyed_node, raw_nodes.items())
    else:
        _nodes = require_sequence(raw_nodes, "nodes")

    built = [_build_node(**node) for node in _normalize_node(*_nodes)]
    result = {node.id: node for node in built}

    if len(result) != len(built):
        raise InvalidPipelineError("duplicate node id")

    return result


def _normalize_endpoint(raw: object, default_port: str) -> Endpoint:
    """Normalizes a ``RawEndpoint`` into a canonical ``node``/``port`` reference."""
    endpoint = require_mapping(raw, "endpoint")
    _reject_unknown(endpoint, Endpoint)
    node = require_str(endpoint.get("node"), "edge endpoint 'node'")
    port = _normalize_port(str(endpoint.get("port", default_port)), default_port)
    _validate_port(port)
    return Endpoint(node, port)


def _resolve_edge_family(family: object, target: Endpoint, **nodes: Node) -> bool:
    """Resolves whether an edge publishes."""
    if family is None:
        publish = isinstance(nodes.get(target.node), SubscribeNode)
    elif family in get_args(EdgeFamily.__value__):
        publish = family == "publish"
    else:
        raise InvalidPipelineError(f"unknown edge family: {family!r}")

    return publish


def _normalize_edge(raw: object, **nodes: Node) -> Edge:
    """Normalizes one ``RawEdge``."""
    edge = require_mapping(raw, "edge")

    if present := _EDGE_ALIASES.intersection(edge):
        raise InvalidPipelineError(f"use 'source'/'target', not {sorted(present)}")

    _reject_unknown(edge, Edge, "type")
    source = _normalize_endpoint(edge.get("source"), "out")
    target = _normalize_endpoint(edge.get("target"), "in")
    family = edge.get("family", edge.get("type"))
    publish = _resolve_edge_family(family, target, **nodes)
    return PublishEdge(source, target) if publish else StreamEdge(source, target)


def _normalize_outputs(raw: object, *edges: Edge, **nodes: Node) -> dict[str, Endpoint]:
    """Normalizes named outputs and defaults to a lone leaf only when omitted."""
    if raw is not None:
        outputs = require_mapping(raw, "outputs")
        result = {
            str(name): _normalize_endpoint(endpoint, "out")
            for name, endpoint in outputs.items()
        }
    else:
        sources = {edge.source.node for edge in edges if edge.family == "stream"}
        leaves = [node_id for node_id in nodes if node_id not in sources]
        result = {"default": Endpoint(leaves[0], "out")} if len(leaves) == 1 else {}

    return result


def _normalize_input(raw: object) -> FrozenJSON:
    """Normalizes an input declaration shorthand into a full JSON Schema mapping."""
    if isinstance(raw, str):
        result = {"type": raw}
    elif is_mapping(raw):
        result = raw
    else:
        raise InvalidPipelineError("input must be a type name or mapping")

    return freeze_mapping(result)


def _normalize_inputs(raw: object) -> JSONSchema:
    """Normalizes declared inputs into name-keyed full JSON Schema mappings."""
    inputs = {} if raw is None else require_mapping(raw, "inputs")
    resolved = {name: _normalize_input(schema) for name, schema in inputs.items()}
    return MappingProxyType(resolved)


def _gen_raw[K, V, R](values: Mapping[K, V], raw: type[R]) -> Iterator[tuple[K, R]]:
    extra = lambda value: {"type": value.family} if isinstance(value, Node) else {}

    for key, _value in values.items():
        yield key, raw(**asdict(_value), **extra(_value))


def _raw_workflow(workflow: Workflow) -> RawWorkflow:
    """Converts a workflow back into a RawWorkflow for re-normalization."""
    edges = dict(zip(count(), workflow.edges, strict=False))

    return RawWorkflow(
        {
            "nodes": dict(_gen_raw(workflow.nodes, RawNode)),
            "edges": [v for _, v in _gen_raw(edges, RawEdge)],
            "outputs": dict(_gen_raw(workflow.outputs, RawEndpoint)),
            "inputs": workflow.inputs,
            "resources": workflow.resources,
            "version": workflow.version,
        }
    )


def normalize_workflow(raw: WorkflowLike) -> Workflow:
    """
    Normalizes a flexible ``WorkflowLike`` into a strict ``Workflow``.

    A :class:`~riko.definitions._workflow.Workflow` is re-normalized through the
    same pipeline rather than trusted, so a hand-built workflow is re-canonicalized and
    normalization is idempotent on its own output.

    This is the one structural normalization boundary: no compiler, runtime, or CLI
    subsystem independently reinterprets shorthand, legacy port names, or
    omitted outputs. It stays contract-free; closed-schema rejection and contract-aware
    sugar belong to the later validation phase.

    Args:

        raw: A ``WorkflowLike`` with ``nodes`` and optional
            ``edges``, ``outputs``, ``inputs``, ``resources``, and ``version``.

    Returns:

        The normalized :class:`~riko.definitions._workflow.Workflow`.

    Examples:

        >>> workflow = normalize_workflow(
        ...     {
        ...         "nodes": [
        ...             {"id": "fetch-1", "name": "fetch"},
        ...             {"name": "write", "type": "write", "backend": "file"},
        ...         ],
        ...         "edges": [
        ...             {"source": {"node": "fetch-1"}, "target": {"node": "write-1"}}
        ...         ],
        ...     }
        ... )
        >>> workflow.nodes["write-1"].backend.value
        'file'
        >>> workflow.outputs["default"]
        Endpoint(node='write-1', port='out')

    """
    source = _raw_workflow(raw) if isinstance(raw, Workflow) else raw
    workflow = require_mapping(source, "workflow")
    _reject_unknown(workflow, Workflow)
    _resources = workflow.get("resources")
    version = workflow.get("version", WORKFLOW_VERSION)
    nodes = _normalize_nodes(workflow.get("nodes", ()))
    _edges = require_sequence(workflow.get("edges", ()), "edges")
    edges = [_normalize_edge(edge, **nodes) for edge in _edges]

    return Workflow(
        nodes=nodes,
        outputs=_normalize_outputs(workflow.get("outputs"), *edges, **nodes),
        inputs=_normalize_inputs(workflow.get("inputs")),
        edges=edges,
        resources=None if _resources is None else require_strlike(_resources),
        version=require_str(version, "workflow 'version'"),
    )


__all__ = ["normalize_workflow"]
