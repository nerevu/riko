# vim: sw=4:ts=4:expandtab
"""
The single authoring-sugar normalization boundary for canonical Workflow v2.

``normalize_workflow`` turns a flexible ``WorkflowSpecLike`` authoring mapping into one
strict canonical ``WorkflowSpec`` so no other subsystem has to reinterpret shorthand. It
is the structural, contract-free pass. Malformed structure raises
``InvalidPipelineError``.

Examples:

    Basic usage::

        >>> from riko.runtime._normalize import normalize_workflow
        >>>
        >>> spec = normalize_workflow(
        ...     {
        ...         "nodes": [{"name": "fetch"}, {"name": "filter"}],
        ...         "edges": [
        ...             {"source": {"node": "fetch-1"}, "target": {"node": "filter-1"}}
        ...         ],
        ...     }
        ... )
        >>> sorted(spec.nodes)
        ['fetch-1', 'filter-1']
        >>> spec.outputs["default"]
        Endpoint(node='filter-1', port='out')

"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, overload

from riko.base._config import INPUT_PORT, OTHER_PORT, OUTPUT_PORT
from riko.base.exceptions import InvalidPipelineError
from riko.coercion._mapping import require_mapping
from riko.coercion._sequences import listize, require_sequence
from riko.definitions._resources import normalize_binding, normalize_resources
from riko.definitions._targets import normalize_keys
from riko.definitions._workflow import (
    ActionNode,
    CacheNode,
    ModuleNode,
    PublishEdge,
    ReadNode,
    StreamEdge,
    SubscribeNode,
    WorkflowSpec,
    WriteNode,
)
from riko.definitions._write import WriteMode
from riko.types._enums import Backends, Formats
from riko.types._guards import is_mapping
from riko.types._workflow import WORKFLOW_VERSION, Endpoint

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypedDict

    from riko.definitions._workflow import Edge, Node
    from riko.types._enums import KeyLike
    from riko.types._workflow import JSONSchema, WorkflowSpecLike

    class _CommonFields(TypedDict):
        """The four fields every node family carries, built once per node."""

        id: str
        name: str
        resources: Mapping[str, str]
        label: str | None


_EDGE_ALIASES = frozenset({"src", "tgt", "from", "to"})


def require_str(value: object, what: str) -> str:
    """Reads the required registered-name field off a node's authoring mapping."""
    if not isinstance(value, str):
        raise InvalidPipelineError(f"{what} must be a str")

    return value


def _legacy_index(suffix: str, default: int) -> int:
    """Reads the trailing number off a legacy ``_OTHER``/``_OUTPUT`` port suffix."""
    return int(suffix) if suffix.isdigit() else default


def _normalize_port(port: str) -> str:
    """Maps a legacy ``_INPUT``/``_OTHER``/``_OUTPUT`` port to the canonical grammar."""
    if port == INPUT_PORT:
        result = "in"
    elif port == OUTPUT_PORT:
        result = "out"
    elif port.startswith(OTHER_PORT):
        result = f"in:{_legacy_index(port[len(OTHER_PORT) :], 1)}"
    elif port.startswith(OUTPUT_PORT):
        result = f"out:{_legacy_index(port[len(OUTPUT_PORT) :], 1) - 1}"
    else:
        result = port

    return result


@overload
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: object,
    what: str,
    *,
    default: E | None = ...,
    strict: Literal[True] = ...,
) -> E: ...
@overload  # noqa: E302
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E],
    value: object,
    what: str,
    *,
    default: E | None = ...,
    strict: bool = ...,
) -> E: ...
@overload  # noqa: E302
def resolve_enum[E: StrEnum](  # noqa: E704
    enum: type[E], value: object, what: str, *, strict: Literal[False]
) -> E | None: ...
def resolve_enum[E: StrEnum](  # noqa: E302
    enum: type[E],
    value: object,
    what: str,
    *,
    default: E | None = None,
    strict: bool = True,
) -> E | None:
    """Resolves a name or member into the given string enum, or rejects it."""
    if value is None and not strict:
        result = default
    else:
        try:
            result = value if isinstance(value, enum) else enum(value)
        except ValueError as error:
            if default is None and strict:
                raise InvalidPipelineError(f"unknown {what}: {value!r}") from error
            else:
                result = default

    return result


def _common_fields(
    node_id: str,
    resources: object = None,
    name: object = None,
    label: object = None,
    **_: object,
) -> _CommonFields:
    """Builds the id, name, resources, and label every node family shares."""
    binding = normalize_binding(resources)

    return {
        "id": node_id,
        "name": require_str(name, "node 'name'"),
        "resources": {} if binding is None else normalize_resources(binding),
        "label": None if label is None else str(label),
    }


def _build_module(
    node_id: str, conf: Mapping[str, object] | None = None, **fields: object
) -> ModuleNode:
    """Builds a :class:`ModuleNode` from an authoring mapping."""
    conf = require_mapping(conf, "node conf") if conf else {}
    return ModuleNode(conf=conf, **_common_fields(node_id, **fields))


def _build_read(
    node_id: str, backend: object = None, fmt: object = None, **fields: object
) -> ReadNode:
    """Builds a :class:`ReadNode` from an authoring mapping."""
    backend = resolve_enum(Backends, backend, "backend")
    fmt = resolve_enum(Formats, fmt, "format", strict=False)
    return ReadNode(backend=backend, fmt=fmt, **_common_fields(node_id, **fields))


def _build_write(
    node_id: str,
    mode: WriteMode | None = None,
    keys: KeyLike | None = None,
    backend: object = None,
    fmt: object = None,
    **fields: object,
) -> WriteNode:
    """Builds a :class:`WriteNode` from an authoring mapping."""
    mode = resolve_enum(WriteMode, mode, "write mode", default=WriteMode.REPLACE)
    fmt = resolve_enum(Formats, fmt, "format", strict=False)

    return WriteNode(
        backend=resolve_enum(Backends, backend, "backend"),
        fmt=fmt,
        mode=mode,
        keys=normalize_keys(keys),
        **_common_fields(node_id, **fields),
    )


def _build_action(
    node_id: str,
    backend: object = None,
    params: Mapping[str, object] | None = None,
    **fields: object,
) -> ActionNode:
    """Builds an :class:`ActionNode` from an authoring mapping."""
    backend = resolve_enum(Backends, backend, "backend")
    params = require_mapping(params, "node params") if params else {}
    return ActionNode(
        backend=backend, params=params, **_common_fields(node_id, **fields)
    )


def _build_cache(
    node_id: str, policy: Mapping[str, object] | None = None, **fields: object
) -> CacheNode:
    """Builds a :class:`CacheNode` from an authoring mapping."""
    policy = require_mapping(policy, "node policy") if policy else {}
    return CacheNode(policy=policy, **_common_fields(node_id, **fields))


def _build_subscribe(
    node_id: str, policy: Mapping[str, object] | None = None, **fields: object
) -> SubscribeNode:
    """Builds a :class:`SubscribeNode` from an authoring mapping."""
    policy = require_mapping(policy, "node policy") if policy else {}
    return SubscribeNode(policy=policy, **_common_fields(node_id, **fields))


_NODE_BUILDERS: Mapping[str, Callable[..., Node]] = {
    "module": _build_module,
    "read": _build_read,
    "write": _build_write,
    "action": _build_action,
    "cache": _build_cache,
    "subscribe": _build_subscribe,
}


def _build_node(
    node_id: str, family: object | None = "module", **fields: object
) -> Node:
    """Dispatches an authoring node mapping to its closed node family builder."""
    family = str(fields.get("type", family))

    if (builder := _NODE_BUILDERS.get(family)) is None:
        raise InvalidPipelineError(f"unknown node family: {family!r}")

    return builder(node_id, **fields)


def _assign_ids(*raw_nodes: object) -> list[tuple[str, Mapping[str, object]]]:
    """Pairs list-authored nodes with explicit or generated ``<name>-<occurrence>``."""
    counts: dict[str, int] = {}
    items: list[tuple[str, Mapping[str, object]]] = []

    for raw_node in raw_nodes:
        fields = require_mapping(raw_node, "node")
        name = fields.get("name")

        if (node_id := fields.get("id")) is None:
            name = require_str(name, "node 'name'")
            counts[name] = counts.get(name, 0) + 1
            node_id = f"{name}-{counts[name]}"

        items.append((str(node_id), fields))

    return items


def _normalize_nodes(raw_nodes: object) -> dict[str, Node]:
    """Normalizes list- or mapping-authored nodes into canonical id-keyed nodes."""
    if isinstance(raw_nodes, Mapping):
        items = [
            (str(node_id), require_mapping(fields, "node"))
            for node_id, fields in raw_nodes.items()
        ]
    else:
        items = _assign_ids(*require_sequence(raw_nodes, "nodes"))

    result = {node_id: _build_node(node_id, **fields) for node_id, fields in items}

    if len(result) != len(items):
        raise InvalidPipelineError("duplicate node id")

    return result


def _normalize_endpoint(raw: object, default_port: str) -> Endpoint:
    """Normalizes an authoring endpoint into a canonical ``node``/``port`` reference."""
    mapping = require_mapping(raw, "endpoint")
    node = require_str(mapping.get("node"), "edge endpoint 'node'")
    port = mapping.get("port", default_port)
    return Endpoint(node, _normalize_port(str(port)))


def _normalize_edge(raw: object, **nodes: Node) -> Edge:
    """Normalizes one authoring edge, choosing the stream or publish family."""
    mapping = require_mapping(raw, "edge")

    if present := _EDGE_ALIASES.intersection(mapping):
        raise InvalidPipelineError(f"use 'source'/'target', not {sorted(present)}")

    source = _normalize_endpoint(mapping.get("source"), "out")
    target = _normalize_endpoint(mapping.get("target"), "in")
    family = mapping.get("family", mapping.get("type"))
    publish = family == "publish" or isinstance(nodes.get(target.node), SubscribeNode)
    return PublishEdge(source, target) if publish else StreamEdge(source, target)


def _normalize_outputs(raw: object, *edges: Edge, **nodes: Node) -> dict[str, Endpoint]:
    """Normalizes named outputs, defaulting to a lone leaf when they are omitted."""
    if raw:
        mapping = require_mapping(raw, "outputs")
        result = {
            str(name): _normalize_endpoint(endpoint, "out")
            for name, endpoint in mapping.items()
        }
    else:
        sources = {edge.source.node for edge in edges if edge.family == "stream"}
        leaves = [node_id for node_id in nodes if node_id not in sources]
        result = {"default": Endpoint(leaves[0], "out")} if len(leaves) == 1 else {}

    return result


def _normalize_input(raw: object) -> JSONSchema:
    """Normalizes an input declaration shorthand into a full JSON Schema mapping."""
    if isinstance(raw, str):
        result: JSONSchema = {"type": raw}
    elif is_mapping(raw):
        result = dict(raw)
    else:
        raise InvalidPipelineError("input must be a type name or JSON Schema mapping")

    return result


def _normalize_inputs(raw: object) -> dict[str, JSONSchema]:
    """Normalizes declared inputs into name-keyed full JSON Schema mappings."""
    mapping = require_mapping(raw, "inputs") if raw else {}
    return {str(name): _normalize_input(schema) for name, schema in mapping.items()}


def normalize_workflow(raw: WorkflowSpecLike) -> WorkflowSpec:
    """
    Normalizes a flexible Workflow v2 authoring mapping into a strict canonical spec.

    This is the one structural normalization boundary: no compiler, runtime, or CLI
    subsystem independently reinterprets authoring shorthand, legacy port names, or
    omitted outputs. It stays contract-free; closed-schema rejection and contract-aware
    sugar belong to the later validation phase.

    Args:

        raw: A ``WorkflowSpecLike`` authoring mapping with ``nodes`` and optional
            ``edges``, ``outputs``, ``inputs``, ``resources``, and ``version``.

    Returns:

        The canonical :class:`~riko.definitions._workflow.WorkflowSpec`.

    Examples:

        >>> spec = normalize_workflow(
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
        >>> spec.nodes["write-1"].backend.value
        'file'
        >>> spec.outputs["default"]
        Endpoint(node='write-1', port='out')

    """
    mapping = require_mapping(raw, "workflow")
    resources = mapping.get("resources")
    nodes = _normalize_nodes(mapping.get("nodes", ()))
    _edges = require_sequence(mapping.get("edges", ()), "edges")
    edges = tuple(_normalize_edge(edge, **nodes) for edge in _edges)

    return WorkflowSpec(
        nodes=nodes,
        edges=edges,
        outputs=_normalize_outputs(mapping.get("outputs"), *edges, **nodes),
        inputs=_normalize_inputs(mapping.get("inputs")),
        resources=tuple(map(str, listize(resources))),
        version=str(mapping.get("version", WORKFLOW_VERSION)),
    )


__all__ = ["normalize_workflow"]
