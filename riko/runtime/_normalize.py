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

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from itertools import count, starmap
from typing import TYPE_CHECKING, Any, cast, get_args

from attrs import AttrsInstance

from riko.base._config import INPUT_PORT, OTHER_PORT, OUTPUT_PORT
from riko.base._graph import edges_to_graph, leaves
from riko.base._iterutils import map_values, unzip
from riko.base.exceptions import InvalidPipelineError
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
    get_family_edges,
)
from riko.types._collections import (
    FrozenDict,
    FrozenJSON,
    freeze_json,
    require_from_attrs,
    require_str,
    require_strlike,
    serialize_attrs,
)
from riko.types._guards import is_mapping, require_mapping, require_sequence
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


_ALIASES: Mapping[str, Mapping[str, str]] = {"node": {"format": "fmt"}, "edge": {}}
_REJECTED_EDGE_KEYS = frozenset({"src", "tgt", "from", "to"})

require_endpoint = require_from_attrs(Endpoint, exclude={"port"})
require_edge = require_from_attrs(Edge)
require_workflow = require_from_attrs(Workflow, exclude={"nodes", "outputs"})


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


def _resolve_aliases[T](raw: Mapping[str, T], kind: str) -> dict[str, T]:
    """Folds each aliased field onto its name and accepts both only when they agree."""
    resolved = dict(raw)

    for alias, name in _ALIASES[kind].items():
        primary, value = resolved.get(name), resolved.pop(alias, None)

        if primary is None and value is not None:
            resolved[name] = value
        elif value is not None and value != primary:
            what = f"{kind} {name!r}/{alias!r}"
            raise InvalidPipelineError(f"conflicting {what}: {primary!r} and {value!r}")

    return resolved


def _build_node(raw: RawNode) -> Node:
    """Dispatches a ``RawNode`` to its closed node family builder."""
    if "type" in raw:
        hint = "a module goes in 'name', a node family in 'family'"
        msg = f"unknown node key 'type': {hint}"
        raise InvalidPipelineError(msg)

    resolved = _resolve_aliases(raw, "node")
    _family = resolved.pop("family", None)
    family = "module" if _family is None else str(_family)

    if (builder := _NODE_BUILDERS.get(family)) is None:
        raise InvalidPipelineError(f"unknown node family: {family!r}")

    require_from_attrs(builder)(resolved)
    return builder(**cast("dict[str, Any]", resolved))


def _gen_node_info(
    raw_nodes: Iterable[object],
) -> Iterator[tuple[str | None, dict[str, Any]]]:
    for raw_node in raw_nodes:
        node = dict(require_mapping(raw_node, "node"))
        taken = None if node.get("id") is None else str(node["id"])
        yield taken, node


def _gen_nodes(raw_nodes: Iterable[object]) -> Iterator[RawNode]:
    """Pairs list-authored nodes with explicit or generated ``<name>-<occurrence>``."""
    _taken, nodes = unzip(_gen_node_info(raw_nodes))
    taken = set(_taken)
    counts: dict[str, int] = defaultdict(int)

    for node in nodes:
        if (node_id := node.pop("id", None)) is None:
            name = require_str(node.get("name"), "node 'name'")
            counts[name] += 1

            while (node_id := f"{name}-{counts[name]}") in taken:
                counts[name] += 1

            taken.add(node_id)

        yield RawNode(id=str(node_id), **node)


def _keyed_node(key: object, raw_node: object) -> dict[str, Any]:
    """Applies the authoritative mapping key and rejects a conflicting inner ``id``."""
    node = dict(require_mapping(raw_node, "node"))
    inner = node.get("id")

    if inner is not None and str(inner) != str(key):
        raise InvalidPipelineError(f"node id {inner!r} conflicts with its key {key!r}")

    node["id"] = key
    return node


def _build_nodes(raw_nodes: object) -> dict[str, Node]:
    """Builds canonical id-keyed nodes from list- or mapping-authored nodes."""
    if isinstance(raw_nodes, Mapping):
        _nodes = starmap(_keyed_node, raw_nodes.items())
    else:
        _nodes = require_sequence(raw_nodes, "nodes")

    built = [_build_node(node) for node in _gen_nodes(_nodes)]
    result = {node.id: node for node in built}

    if len(result) != len(built):
        raise InvalidPipelineError("duplicate node id")

    return result


def resolve_port(port: object, default: str) -> str:
    """Resolves an authored endpoint port."""
    return default if port is None else str(port)


def _normalize_endpoint(raw: object, default_port: str) -> Endpoint:
    """Normalizes a ``RawEndpoint`` into a canonical ``node``/``port`` reference."""
    endpoint = require_endpoint(require_mapping(raw, "endpoint"))
    node = require_str(endpoint.get("node"), "edge endpoint 'node'")
    resolved = resolve_port(endpoint.get("port"), default_port)
    port = _normalize_port(resolved, default_port)
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
    _edge = require_mapping(raw, "edge")

    if present := _REJECTED_EDGE_KEYS.intersection(_edge):
        raise InvalidPipelineError(f"use 'source'/'target', not {sorted(present)}")

    resolved = _resolve_aliases(_edge, "edge")
    edge = require_edge(resolved)
    source = _normalize_endpoint(edge["source"], "out")
    target = _normalize_endpoint(edge["target"], "in")
    publish = _resolve_edge_family(edge.get("family"), target, **nodes)
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
        pairs = ((e.source.node, e.target.node) for e in get_family_edges(edges))
        ends = leaves(edges_to_graph(pairs, *nodes))
        result = {"default": Endpoint(ends[0], "out")} if len(ends) == 1 else {}

    return result


def _require_input(raw: object) -> str | Mapping[str, object]:
    """Narrows an input declaration to a type name or schema mapping, or raises."""
    if not (isinstance(raw, str) or is_mapping(raw)):
        raise InvalidPipelineError("input must be a type name or mapping")

    return raw


def _normalize_input(raw: object) -> FrozenDict[str, FrozenJSON]:
    """Normalizes an input declaration shorthand into a full JSON Schema mapping."""
    declaration = _require_input(raw)
    result = {"type": declaration} if isinstance(declaration, str) else declaration
    return freeze_json(result)


def _normalize_inputs(raw: object) -> dict[str, FrozenDict[str, FrozenJSON]]:
    """Normalizes input declarations into name-keyed full JSON Schema mappings."""
    inputs = {} if raw is None else require_mapping(raw, "inputs")
    return map_values(_normalize_input, inputs)


def _gen_raw[K, V: AttrsInstance, R](
    values: Mapping[K, V], raw: type[R]
) -> Iterator[tuple[K, R]]:
    extra = lambda value: {"family": value.family} if isinstance(value, Node) else {}

    for key, _value in values.items():
        yield key, raw(**serialize_attrs(_value, recurse=True), **extra(_value))


def _raw_workflow(workflow: Workflow) -> RawWorkflow:
    """Converts a workflow back into a RawWorkflow for re-normalization."""
    edges = dict(zip(count(), workflow.edges, strict=False))

    return RawWorkflow(
        {
            "nodes": dict(_gen_raw(workflow.nodes, RawNode)),
            "edges": [v for _, v in _gen_raw(edges, RawEdge)],
            "outputs": dict(_gen_raw(workflow.outputs, RawEndpoint)),
            "inputs": map_values(_require_input, workflow.inputs),
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
        ...             {"name": "write", "family": "write", "backend": "file"},
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
    workflow = require_workflow(require_mapping(source, "workflow"))
    _resources = workflow.get("resources")
    version = workflow.get("version", WORKFLOW_VERSION)
    nodes = _build_nodes(workflow.get("nodes", ()))
    _edges = require_sequence(workflow.get("edges", ()), "edges")
    edges = [_normalize_edge(edge, **nodes) for edge in _edges]

    return Workflow(
        nodes=nodes.values(),
        outputs=_normalize_outputs(workflow.get("outputs"), *edges, **nodes),
        inputs=_normalize_inputs(workflow.get("inputs")),
        edges=edges,
        resources=() if _resources is None else require_strlike(_resources),
        version=require_str(version, "workflow 'version'"),
    )


__all__ = ["normalize_workflow", "resolve_port"]
