# vim: sw=4:ts=4:expandtab
"""
The single shorthand normalization boundary for ``Workflow`` graphs.

Flexible workflow mappings are turned into the strict nodes, edges, outputs, and input
schemas ``Workflow.from_raw`` builds a ``Workflow`` from. No other subsystem has to
reinterpret shorthand. This is the structural, contract-free pass. Malformed structure
raises ``InvalidPipelineError``.

"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from functools import partial
from itertools import count, starmap
from typing import TYPE_CHECKING, Any, cast, get_args

from attrs import AttrsInstance

from riko.base._config import DEFAULT_OUTPUT, INPUT_PORT, OTHER_PORT, OUTPUT_PORT
from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_keys_and_values, map_values
from riko.base._graph import edges_to_graph, leaves
from riko.base._guards import require_listlike, require_mapping
from riko.base._iterutils import gen_non_null, unzip
from riko.base._recordutils import serialize_attrs
from riko.base._require_guards import (
    require_from_attrs,
    require_from_typed_dict,
    require_str,
)
from riko.types._frozendict import normalize_mapping
from riko.types._workflow import (
    PORT_DIRECTIONS,
    EdgeFamily,
    Endpoint,
    NodeId,
    Port,
    PortEdge,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
    parse_port,
)

from ._inputs import normalize_input_schema
from ._nodes import (
    ActionNode,
    CacheNode,
    CallableNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    RikoNode,
    StreamEdge,
    SubscribeNode,
    WriteNode,
    get_family_edges,
)

if TYPE_CHECKING:
    from ._workflow_definition import (
        EdgeLike,
        EndpointLike,
        InputSchemas,
        InputSchemasLike,
        NodeLike,
        NodesLike,
        Outputs,
        OutputsLike,
        PortEdges,
        RikoNodeCollection,
        Workflow,
    )

_ALIASES: Mapping[str, Mapping[str, str]] = {"node": {"format": "fmt"}, "edge": {}}
_REJECTED_EDGE_KEYS = frozenset({"src", "tgt", "from", "to"})

_NODE_BUILDERS: Mapping[str, type[RikoNode]] = {
    "module": ModuleNode,
    "read": ReadNode,
    "write": WriteNode,
    "action": ActionNode,
    "cache": CacheNode,
    "subscribe": SubscribeNode,
}

require_raw_endpoint = require_from_typed_dict(RawEndpoint, "Endpoint")
require_raw_edge = require_from_typed_dict(RawEdge, "PortEdge")
require_raw_workflow = require_from_typed_dict(RawWorkflow, "Workflow")


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
    if not port or port in PORT_DIRECTIONS:
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


def _build_node(raw: NodeLike) -> RikoNode:
    """Dispatches a ``RawNode`` to its closed node family builder."""
    if isinstance(raw, RikoNode):
        node = raw
    elif "type" in raw:
        hint = "a module goes in 'name', a node family in 'family'"
        msg = f"unknown node key 'type': {hint}"
        raise InvalidPipelineError(msg)
    else:
        resolved = _resolve_aliases(raw, "node")
        _family = resolved.pop("family", None)
        family = "module" if _family is None else str(_family)

        if family == CallableNode.family:
            msg = "a workflow document cannot hold a callable node. "
            msg += "Chain the callable with Pipeline.map instead"
            raise InvalidPipelineError(msg)
        elif (builder := _NODE_BUILDERS.get(family)) is None:
            raise InvalidPipelineError(f"unknown node family: {family!r}")

        require_from_attrs(builder)(resolved)
        node = builder(**cast("dict[str, Any]", resolved))

    return node


def get_free_occurrence(name: str, taken: Iterable[str], start: int = 1) -> int:
    """
    Gets the first occurrence number from ``start`` whose ``<name>-<n>`` id is free.

    Args:

        name: The node name the id is based on.
        taken: The ids already in use.

    Kwargs:

        start: The first occurrence number to try.

    Returns:

        The occurrence number of the first ``<name>-<n>`` not in ``taken``.

    Examples:

        >>> get_free_occurrence("fetch", ("fetch-1", "fetch-2"))
        3
        >>> get_free_occurrence("fetch", ["fetch-2"])
        1
        >>> get_free_occurrence("fetch", ["fetch-1"], start=3)
        3

    """
    _taken = frozenset(taken)
    return next(n for n in count(start) if f"{name}-{n}" not in _taken)


def _gen_node_info(raw_nodes: Iterable[NodeLike]) -> Iterator[tuple[object, NodeLike]]:
    for raw_node in raw_nodes:
        node_id = raw_node.id if isinstance(raw_node, RikoNode) else raw_node.get("id")
        yield node_id, raw_node


def _gen_nodes(raw_nodes: Iterable[NodeLike]) -> Iterator[NodeLike]:
    """Pairs list-authored nodes with explicit or generated ``<name>-<occurrence>``."""
    _taken, nodes = unzip(_gen_node_info(raw_nodes))
    taken = set(gen_non_null(_taken, func=str))
    counts: dict[str, int] = defaultdict(int)

    for node in nodes:
        if isinstance(node, RikoNode):
            yield node
        else:
            if (node_id := node.get("id")) is None:
                name = require_str(node.get("name"), "node 'name'")
                counts[name] = get_free_occurrence(name, taken, counts[name] + 1)
                node_id = f"{name}-{counts[name]}"
                taken.add(node_id)

            yield {"id": str(node_id)} | {k: v for k, v in node.items() if k != "id"}


def _keyed_node(key: str, raw_node: NodeLike) -> NodeLike:
    """Applies the authoritative mapping key and rejects a conflicting inner ``id``."""
    if isinstance(raw_node, RikoNode):
        inner: object = raw_node.id
        keyed: NodeLike = raw_node
    else:
        inner = raw_node.get("id")
        keyed = {**raw_node, "id": key}

    if inner is not None and str(inner) != str(key):
        raise InvalidPipelineError(f"node id {inner!r} conflicts with its key {key!r}")

    return keyed


def build_nodes(raw_nodes: NodesLike) -> RikoNodeCollection:
    """
    Builds canonical id-keyed nodes from list- or mapping-authored nodes.

    A listed node without an ``id`` gets ``<name>-<occurrence>``. A mapping key is the
    node's id.

    Args:

        raw_nodes: The authored nodes, listed or keyed by id.

    Returns:

        The built nodes keyed by id.

    Raises:

        InvalidPipelineError: If a node is malformed or two nodes share an id.

    Examples:

        >>> list(build_nodes([{"name": "fetch"}, {"name": "fetch"}]))
        ['fetch-1', 'fetch-2']

    """
    _nodes: Iterable[NodeLike]

    if isinstance(raw_nodes, Mapping):
        _nodes = starmap(_keyed_node, raw_nodes.items())
    else:
        _nodes = (
            node if isinstance(node, RikoNode) else require_mapping(node, "node")
            for node in require_listlike(raw_nodes, "nodes")
        )

    built = [_build_node(node) for node in _gen_nodes(_nodes)]
    result = {node.id: node for node in built}

    if len(built) != len(result):
        raise InvalidPipelineError("duplicate node id")

    return result


def resolve_port(port: Port | None, default: Port) -> Port:
    """Resolves an authored endpoint port."""
    return default if port is None else str(port)


def _normalize_endpoint(raw: EndpointLike, default_port: str) -> Endpoint:
    """Normalizes an authored endpoint into a canonical ``node``/``port`` reference."""
    if isinstance(raw, Endpoint):
        result = raw
    else:
        endpoint = require_raw_endpoint(require_mapping(raw, "endpoint"))
        node = require_str(endpoint.get("node"), "edge endpoint 'node'")
        resolved = resolve_port(endpoint.get("port"), default_port)
        port = _normalize_port(resolved, default_port)
        _validate_port(port)
        result = Endpoint(node, port)

    return result


def _resolve_edge_family(
    family: str | None, target: Endpoint, **nodes: RikoNode
) -> bool:
    """Resolves whether an edge publishes."""
    if family is None:
        publish = isinstance(nodes.get(target.node), SubscribeNode)
    elif family in get_args(EdgeFamily.__value__):
        publish = family == "publish"
    else:
        raise InvalidPipelineError(f"unknown edge family: {family!r}")

    return publish


def normalize_edge(raw: EdgeLike, **nodes: RikoNode) -> PortEdge:
    """
    Normalizes an authored edge into a stream or publish edge.

    An edge without a ``family`` publishes when its target is a subscribe node.

    Args:

        raw: The authored edge: ``source`` and ``target`` endpoints, and an optional
            ``family``.

    Kwargs:

        nodes: The workflow nodes keyed by id.

    Returns:

        The ``StreamEdge`` or ``PublishEdge``.

    Raises:

        InvalidPipelineError: If the edge or an endpoint is malformed.

    Examples:

        >>> edge = normalize_edge({"source": {"node": "a"}, "target": {"node": "b"}})
        >>> edge.source
        Endpoint(node='a', port='out')
        >>> edge.target
        Endpoint(node='b', port='in')

    """
    if isinstance(raw, PortEdge):
        result = raw
    elif present := _REJECTED_EDGE_KEYS.intersection(raw):
        raise InvalidPipelineError(f"use 'source'/'target', not {sorted(present)}")
    else:
        edge = require_raw_edge(_resolve_aliases(raw, "edge"))
        source = _normalize_endpoint(edge["source"], "out")
        target = _normalize_endpoint(edge["target"], "in")
        publish = _resolve_edge_family(edge.get("family"), target, **nodes)
        result = PublishEdge(source, target) if publish else StreamEdge(source, target)

    return result


def normalize_outputs(
    raw: OutputsLike | None, edges: PortEdges, *node_ids: NodeId
) -> Outputs:
    """
    Normalizes the workflow outputs (endpoints keyed by name).

    Omitted outputs default to the lone leaf node's ``out`` port, or to none when
    several nodes are leaves.

    Args:

        raw: The authored outputs keyed by name, or ``None`` when omitted.
        edges: The normalized workflow edges.

    Kwargs:

        node_ids: The workflow node ids.

    Returns:

        The output endpoints keyed by name.

    Raises:

        InvalidPipelineError: If the outputs or an endpoint are malformed.

    Examples:

        >>> normalize_outputs(None, [], "fetch-1")
        {'default': Endpoint(node='fetch-1', port='out')}
        >>> normalize_outputs({"errors": {"node": "a", "port": "out:1"}}, [], "a")
        {'errors': Endpoint(node='a', port='out:1')}

    """
    if raw is None:
        pairs = ((e.source.node, e.target.node) for e in get_family_edges(edges))
        ends = leaves(edges_to_graph(pairs, *node_ids))
        result = {DEFAULT_OUTPUT: Endpoint(ends[0], "out")} if len(ends) == 1 else {}
    else:
        outputs = require_mapping(raw, "outputs")
        normalize = partial(_normalize_endpoint, default_port="out")
        result = map_keys_and_values(str, normalize, outputs)

    return result


def normalize_input_schemas(raw: InputSchemasLike | None) -> InputSchemas:
    """
    Normalizes the inputs' schemas into full JSON Schemas.

    Args:

        raw: Each input's schema (a type name or JSON Schema) keyed by input name, or
            ``None``.

    Returns:

        Each input's JSON Schema keyed by input name.

    Raises:

        InvalidPipelineError: If ``raw`` is not a mapping or an input's schema is
            neither a type name nor a mapping.

    Examples:

        >>> schemas = normalize_input_schemas({"limit": "integer"})
        >>> {k: dict(v) for k, v in schemas.items()}
        {'limit': {'type': 'integer'}}

    """
    schemas = normalize_mapping(raw, "input_schemas", strict=True)
    return map_values(normalize_input_schema, schemas)


def _gen_raw[K, V: AttrsInstance, R](
    values: Mapping[K, V], raw: type[R]
) -> Iterator[tuple[K, R]]:
    def extra(value: V) -> dict[str, str]:
        if isinstance(value, (RikoNode, PortEdge)):
            result = {"family": value.family}
        else:
            result = {}

        return result

    for key, _value in values.items():
        yield key, raw(**serialize_attrs(_value, recurse=True), **extra(_value))


def build_raw_workflow(flow: Workflow) -> RawWorkflow:
    """
    Builds the shorthand mapping a built workflow normalizes from.

    Args:

        flow: The ``Workflow`` to convert.

    Returns:

        The ``RawWorkflow`` describing the same graph.

    Raises:

        InvalidPipelineError: If the workflow has a callable node.

    """
    flow.validate_document_nodes()
    edges = dict(zip(count(), flow.edges, strict=False))

    return RawWorkflow(
        {
            "nodes": dict(_gen_raw(flow.nodes, RawNode)),
            "edges": [v for _, v in _gen_raw(edges, RawEdge)],
            "outputs": dict(_gen_raw(flow.outputs, RawEndpoint)),
            "input_schemas": flow.input_schemas,
            "resources": flow.resources,
            "version": flow.version,
        }
    )


__all__ = [
    "build_nodes",
    "build_raw_workflow",
    "normalize_edge",
    "normalize_input_schemas",
    "normalize_outputs",
    "require_raw_workflow",
    "resolve_port",
]
