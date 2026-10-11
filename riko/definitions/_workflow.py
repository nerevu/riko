# vim: sw=4:ts=4:expandtab
"""
The immutable ``Workflow`` graph model and the ``PipelineDefinition`` around it.

Six closed node families (``ModuleNode``/``ReadNode``/``WriteNode``/``CacheNode``/
``ActionNode``/``SubscribeNode``) and two edge families (``StreamEdge``/``PublishEdge``)
compose a ``Workflow`` graph. This is the structural immutable definition that wraps the
nodes and edges.

Nodes carry declarative intent, never execution state, and no node runs here.
``WriteNode`` and ``ActionNode`` carry a ``backend`` and serialization ``fmt`` rather
than a live resource or write session.

Examples:

    Basic usage::

        >>> from riko.definitions._workflow import (
        ...     ModuleNode,
        ...     PipelineDefinition,
        ...     Workflow,
        ... )
        >>> from riko.types._workflow import Endpoint
        >>>
        >>> workflow = Workflow(
        ...     nodes=[ModuleNode(id="fetch-1", name="fetch")],
        ...     outputs={"default": Endpoint("fetch-1", "out")},
        ... )
        >>> PipelineDefinition(workflow).workflow.outputs["default"]
        Endpoint(node='fetch-1', port='out')

"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from functools import cached_property, partial
from inspect import isawaitable
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Literal,
    Self,
    TypeGuard,
    cast,
    overload,
)

from attrs import define, evolve, field, fields
from typing_extensions import TypeVar

from riko.base.exceptions import InvalidPipelineError
from riko.types._collections import (
    FrozenConf,
    FrozenDict,
    FrozenJSON,
    FrozenOptions,
    FrozenParams,
    FrozenPolicy,
    def_from_require,
    def_from_typed_dict,
    freeze_json,
    instances_freezer,
    mapping_converter,
    narrow_def_from_require,
    narrow_from_require,
    normalize_strs,
    optional_mapping_converter,
    require_binding,
    require_from_typed_dict,
    require_instance,
    require_instances,
    require_str,
    validator_from_require,
    validator_from_typed_dict,
)
from riko.types._compiler import DagModule, Embed, EmbedRef, PipeModule
from riko.types._enums import Backends, Formats, ModuleNameLike
from riko.types._guards import (
    is_mapping,
    is_streamlike,
    require_mapping,
    require_sequence,
)
from riko.types._sentinels import MISSING, MissingType
from riko.types._targets import resolve_enum
from riko.types._workflow import (
    WORKFLOW_VERSION,
    Edge,
    Endpoint,
    GraphEdge,
    GraphIndex,
    NodeId,
    RawWorkflow,
    parse_port,
)
from riko.types.modules import (
    AnyModuleConf,
    CallOptions,
    Conf,
    ConfValues,
    MaybeFrozenConf,
    OptionValues,
    WriteConf,
)

from ._context import Context
from ._execution import DEF_EXECUTION_SETTINGS, ExecutionSettings
from ._resource_types import ResourcesLike
from ._targets import build_write
from ._write import WriteMode

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from riko.types._enums import ConcurrencyLike, ExecutorLike, FmtLike, StrLike
    from riko.types._events import EventSink
    from riko.types._resource import LifecycleFactory
    from riko.types._streams import SourceLike
    from riko.types._workflow import EdgeFamily, NodeFamily

    from ._resource_definition import ReusableResource
    from ._resource_types import ResourceDefinition
    from ._write import Destination

_FROZEN_OPTIONS: FrozenOptions = FrozenDict()
_FROZEN_PARAMS: FrozenDict[str, FrozenJSON] = FrozenDict()
_FROZEN_POLICY: FrozenDict[str, FrozenJSON] = FrozenDict()
_EMPTY_INPUTS: FrozenDict[str, FrozenJSON] = FrozenDict()
_EMPTY_OUTPUTS: FrozenDict[str, Endpoint] = FrozenDict()
_EMPTY_NODES: FrozenDict[NodeId, Node] = FrozenDict()
_EMPTY_EDGES: tuple[Edge, ...] = ()
_EMPTY_RESOURCES: tuple[str, ...] = ()
EMPTY_BINDINGS: FrozenDict[str, str] = FrozenDict()
FROZEN_CONF: FrozenConf = FrozenDict()

T = TypeVar("T", default=Any)
type WorkflowLike = Workflow | RawWorkflow | Mapping[str, object]
type ConfInput = MaybeFrozenConf | Mapping[str, ConfValues]
type OptionsInput = CallOptions | FrozenOptions | Mapping[str, OptionValues]
type NodesInput = Iterable[Node]
type OutputsInput = Mapping[str, Endpoint]

_WRITE_MODES = {"w": WriteMode.REPLACE, "a": WriteMode.APPEND}
_normalize_backend = partial(resolve_enum, Backends)
_normalize_format = partial(resolve_enum, Formats, strict=False)
_normalize_mode = partial(resolve_enum, WriteMode, default=WriteMode.REPLACE)

optional_mapping = def_from_require(require_mapping)
optional_str = narrow_def_from_require(require_str)

require_embed_ref = require_from_typed_dict(EmbedRef)
keys_converter = partial(normalize_strs, what="WriteNode 'keys'")
endpoint_freezer = instances_freezer(Endpoint, "Workflow output")
json_converter = partial(optional_mapping_converter, freeze_json)
outputs_converter = mapping_converter(
    endpoint_freezer, OutputsInput, what="Workflow 'outputs'"
)
binding_converter = narrow_def_from_require(
    require_binding, EMPTY_BINDINGS, "node 'resources'", accepted=ResourcesLike
)
conf_converter = partial(json_converter, ConfInput)
options_converter = json_converter(OptionsInput, what="ModuleNode 'options'")
inputs_converter = mapping_converter(freeze_json, what="Workflow 'inputs'")

resource_names_converter = partial(
    normalize_strs, what="Workflow 'resources'", strict=True
)
_module_conf_converter = conf_converter(what="ModuleNode 'conf'")


def _edges_converter(value: Iterable[Edge]) -> tuple[Edge, ...]:
    """Requires every workflow edge to be an ``Edge``."""
    edges = require_sequence(value, "Workflow 'edges'")
    return tuple(require_instances(Edge, edges, "Workflow edge"))


def _is_source(value: object) -> TypeGuard[SourceLike]:
    """A seed on the left of ``|``: a stream, an async stream, or an awaitable."""
    seedlike = is_streamlike(value) or isawaitable(value)
    return seedlike and not isinstance(value, PipelineDefinition)


def _is_module_pair(value: object) -> TypeGuard[tuple[str, AnyModuleConf]]:
    """A ``(name, conf)`` pair on the right of ``|``."""
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], str)
        and is_mapping(value[1])
    )


def _normalize_embed_conf(
    value: Mapping[str, object], what: str | None = None, **_
) -> Mapping[str, object]:
    """Fills an omitted embed ``conf`` with an empty configuration."""
    return value if "conf" in value else {**value, "conf": {}}


def parse_write_mode(mode: str) -> WriteMode:
    """Translates a ``PipeDef`` file-open write mode into a ``WriteMode``."""
    head = mode[:1].lower()

    if (write_mode := _WRITE_MODES.get(head)) is None:
        msg = f"cannot migrate pipe definition write mode: {mode!r}"
        raise InvalidPipelineError(msg)

    return write_mode


def require_embed_fields(value: Embed, what: str = "embed") -> Embed:
    """Validates an Embed's keys."""
    require_str(value["name"], f"{what} 'name'")
    require_mapping(value["conf"], f"{what} 'conf'")
    optional_str(value.get("id"))
    return value


def require_embed_ref_fields(value: EmbedRef, what: str = "embed") -> EmbedRef:
    """Validates an EmbedRef's keys."""
    require_str(value["type"], f"{what} 'type'")
    require_str(value["id"], f"{what} 'id'")
    return value


def require_dag_name(value: DagModule, what: str = "dag module") -> str:
    """
    Requires a ``DagModule``'s module name, read from ``name`` or its older ``type``.

    Raises:

        InvalidPipelineError: If neither key is present, or both are and disagree.

    """
    name, type_ = value.get("name"), value.get("type")

    if name is None and type_ is None:
        raise InvalidPipelineError(f"{what} needs a 'name'")
    elif name is not None and type_ is not None and name != type_:
        msg = f"conflicting {what} 'name'/'type': {name!r} and {type_!r}"
        raise InvalidPipelineError(msg)

    return require_str(type_ if name is None else name, f"{what} 'name'")


def require_dag_fields(value: DagModule, what: str = "dag module") -> DagModule:
    """Validates a ``DagModule``'s keys."""
    optional_str(value.get("id"))
    require_dag_name(value, what)
    optional_mapping(value.get("conf"))
    return value


def resolve_write_mode(value: WriteConf, what: str = "write conf") -> WriteMode | None:
    """Translates a ``WriteConf``'s mode into a ``WriteMode`` (``None`` when absent)."""
    mode = optional_str(value.get("mode"))
    return None if mode is None else parse_write_mode(mode)


def require_v1_pipe_fields(value: PipeModule, what: str = "module") -> PipeModule:
    """Validates a ``PipeModule``'s keys."""
    require_str(value["id"], f"{what} 'id'")
    require_str(value["type"], f"{what} 'type'")
    require_mapping(value["conf"], f"{what} 'conf'")
    return value


def require_v1_loop_fields(value: PipeModule, what: str = "loop module") -> PipeModule:
    """Validates a ``loop`` ``PipeModule``'s embed."""
    embed = require_mapping(value.get("embed"), f"{what} 'embed'")
    require_embed_ref_fields(require_embed_ref(embed))
    return value


@define(frozen=True, slots=True, kw_only=True)
class Node:
    """The identity, resource bindings, and label every node family carries."""

    family: ClassVar[NodeFamily]
    id: NodeId = field(validator=validator_from_require(require_str))
    name: str = field(converter=narrow_from_require(require_str))
    resources: FrozenDict[str, str] = field(
        default=EMPTY_BINDINGS, converter=binding_converter
    )
    label: str | None = field(default=None, converter=optional_str)

    @property
    def referenced_resources(self) -> set[str]:
        """Collects the Context resource names this node binds."""
        return set(self.resources.values())


@define(frozen=True, slots=True, kw_only=True)
class ModuleNode(Node):
    """
    A module node: any module, including split/branch/route/union/join/loop.

    Attributes:

        conf: the configuration the node's own module parses.

        options: the call options forwarded to the module callable itself, such as
            ``emit``, ``assign``, ``field``, and ``count``.

        embed: names the module a ``loop`` runs once per item, together with that
            module's own configuration.

    """

    family: ClassVar[NodeFamily] = "module"
    conf: FrozenConf = field(default=FROZEN_CONF, converter=_module_conf_converter)
    options: FrozenOptions = field(
        default=_FROZEN_OPTIONS,
        converter=options_converter,
        validator=validator_from_typed_dict(CallOptions),
    )
    embed: Embed | None = field(
        default=None,
        converter=[
            def_from_require(require_mapping, what="ModuleNode 'embed'"),
            def_from_require(_normalize_embed_conf),
            def_from_typed_dict(Embed, what="ModuleNode 'embed'"),
            freeze_json,
        ],
        validator=validator_from_require(require_embed_fields, optional=True),
    )


@define(frozen=True, slots=True, kw_only=True)
class ReadNode(Node):
    """A node that acquires records from a backend, interpreting them via a format."""

    family: ClassVar[NodeFamily] = "read"
    backend: Backends = field(converter=_normalize_backend)
    fmt: Formats | None = field(default=None, converter=_normalize_format)


@define(frozen=True, slots=True, kw_only=True)
class WriteNode(Node):
    """A node that writes an item stream to a backend destination with a format."""

    family: ClassVar[NodeFamily] = "write"
    backend: Backends = field(converter=_normalize_backend)
    dest: str | None = field(default=None, converter=optional_str)
    fmt: Formats | None = field(default=None, converter=_normalize_format)
    mode: WriteMode = field(default=WriteMode.REPLACE, converter=_normalize_mode)
    keys: tuple[str, ...] = field(default=(), converter=keys_converter)


@define(frozen=True, slots=True, kw_only=True)
class ActionNode(Node):
    """A node that runs a provider command that is not a data write."""

    family: ClassVar[NodeFamily] = "action"
    backend: Backends = field(converter=_normalize_backend)
    params: FrozenParams = field(
        default=_FROZEN_PARAMS, converter=json_converter(what="ActionNode 'params'")
    )


@define(frozen=True, slots=True, kw_only=True)
class CacheNode(Node):
    """A node carrying cache identity and policy, never cache contents."""

    family: ClassVar[NodeFamily] = "cache"
    policy: FrozenPolicy = field(
        default=_FROZEN_POLICY, converter=json_converter(what="CacheNode 'policy'")
    )


@define(frozen=True, slots=True, kw_only=True)
class SubscribeNode(Node):
    """A node owning subscription policy for a published stream."""

    family: ClassVar[NodeFamily] = "subscribe"
    policy: FrozenPolicy = field(
        default=_FROZEN_POLICY, converter=json_converter(what="SubscribeNode 'policy'")
    )


@define(frozen=True, slots=True)
class StreamEdge(Edge):
    """A stream edge delivering items from a source port to a target port."""

    family: ClassVar[EdgeFamily] = "stream"


@define(frozen=True, slots=True)
class PublishEdge(Edge):
    """A publish edge delivering a producer's output stream to a subscribe node."""

    family: ClassVar[EdgeFamily] = "publish"


def get_family_edges(
    edges: Iterable[Edge], family: EdgeFamily = "stream"
) -> list[Edge]:
    """
    Selects the edges of one family, in listing order.

    Args:

        edges: The edges to select from.
        family: The edge family to keep.

    Returns:

        The ``family`` edges among ``edges``.

    Examples:

        >>> from riko.types._workflow import Endpoint
        >>>
        >>> end = Endpoint("a", "out")
        >>> edges = [StreamEdge(end, end), PublishEdge(end, end)]
        >>> [edge.family for edge in get_family_edges(edges, "publish")]
        ['publish']

    """
    return [edge for edge in edges if edge.family == family]


def require_module_node(value: Node, what: str | None = None, **_) -> ModuleNode:
    if not isinstance(value, ModuleNode):
        what = value.family if what is None else what
        raise InvalidPipelineError(f"{what} node execution is not yet supported")

    return value


def nodes_converter(value: NodesInput) -> FrozenDict[NodeId, Node]:
    """Keys each workflow node by its id, rejecting a mapping or a repeated id."""
    if value is _EMPTY_NODES:
        result = _EMPTY_NODES
    else:
        _nodes = require_sequence(value, "Workflow 'nodes'")
        nodes = list(require_instances(Node, _nodes, "Workflow node"))
        keyed = {node.id: node for node in nodes}

        if len(keyed) < len(nodes):
            raise InvalidPipelineError("Workflow 'nodes' must not repeat a node id")

        result = FrozenDict.from_frozen(keyed)

    return result


@define(frozen=True, slots=True)
class Workflow:
    """
    The strict in-memory workflow graph: nodes, edges, outputs, and input declarations.

    Construction canonicalizes field-local representation details such as immutable
    mappings and resource-name shorthand. Does not perform shorthand normalization
    or closed-schema rejection. Cross-field graph validity is checked explicitly by
    ``validate()``.

    Attributes:

        nodes: The graph nodes (given as an iterable and stored keyed by node id).
        edges: The stream and publish edges, in listing order.
        outputs: The workflow outputs: named endpoints the workflow exposes.
        inputs: The declared JSON Schemas.
        resources: The workflow declared resources (must include each one a node binds).
        version: The workflow format version.

    Examples:

        >>> workflow = Workflow(
        ...     nodes=[ModuleNode(id="fetch-1", name="fetch")],
        ...     outputs={"default": Endpoint("fetch-1", "out")},
        ...     resources="db",
        ... )
        >>> workflow.resources
        ('db',)
        >>> workflow.isvalid
        True

    """

    nodes: FrozenDict[NodeId, Node] = field(
        default=_EMPTY_NODES, converter=nodes_converter
    )
    outputs: FrozenDict[str, Endpoint] = field(
        default=_EMPTY_OUTPUTS, converter=outputs_converter
    )
    inputs: FrozenDict[str, FrozenJSON] = field(
        default=_EMPTY_INPUTS, converter=inputs_converter
    )
    edges: tuple[Edge, ...] = field(default=_EMPTY_EDGES, converter=_edges_converter)
    resources: tuple[str, ...] = field(
        default=_EMPTY_RESOURCES, converter=resource_names_converter
    )
    version: str = WORKFLOW_VERSION

    def family_sources(self, family: EdgeFamily = "stream") -> Counter[tuple[str, str]]:
        edges = get_family_edges(self.edges, family)
        return Counter((edge.source.node, edge.source.port) for edge in edges)

    def family_ports(self, family: EdgeFamily = "stream") -> Counter[tuple[str, str]]:
        return Counter(edge.port for edge in get_family_edges(self.edges, family))

    def _gen_edge_target_mismatches(self) -> Iterator[str]:
        """Detects a publish/subscribe mismatch between an edge and its target node."""
        for edge in self.edges:
            node = self.nodes.get(edge.target.node)

            if (edge.family == "publish") != isinstance(node, SubscribeNode):
                yield edge.target.node

    def _gen_misdirected_ports(self) -> Iterator[str]:
        """Describes each endpoint whose port faces the wrong way for its role."""
        sources = ((edge.source, "out") for edge in self.edges)
        targets = ((edge.target, "in") for edge in self.edges)
        outputs = ((ref, "out") for ref in self.outputs.values())

        for endpoint, direction in chain(sources, targets, outputs):
            try:
                parsed = parse_port(endpoint.port)
            except ValueError as error:
                raise InvalidPipelineError(str(error)) from error

            if parsed.direction != direction:
                yield f"{endpoint} is not an {direction!r} port"

    @cached_property
    def graph_edges(self) -> tuple[GraphEdge, ...]:
        """Flattens each edge into the node-and-port record the graph index reads."""
        return tuple(
            GraphEdge(e.source.node, e.target.node, e.source.port, e.target.port)
            for e in self.edges
        )

    @cached_property
    def index(self) -> GraphIndex:
        """Interprets the topology once; edges and outputs name declared nodes."""
        return GraphIndex(self.nodes, self.graph_edges, self.outputs)

    @property
    def is_empty(self) -> bool:
        """Whether the workflow declares no nodes, edges, or outputs."""
        return not (self.nodes or self.edges or self.outputs)

    @property
    def endpoints(self) -> list[Endpoint]:
        """Collect every endpoint referenced by an edge or named output."""
        ends = chain.from_iterable((edge.source, edge.target) for edge in self.edges)
        return list(chain(ends, self.outputs.values()))

    @property
    def referenced_resources(self) -> set[str]:
        """Collects the Context resource names the workflow's nodes bind."""
        nodes = self.nodes.values()
        return set(chain.from_iterable(node.referenced_resources for node in nodes))

    def validate(self) -> None:
        """
        Validate workflow graph structure and references.

        Raises:

            InvalidPipelineError: If the graph is structurally invalid: an unsupported
                version, an empty node set, a dangling
                edge or output reference, more than one stream edge into a port, a
                publish/subscribe edge mismatch, a misdirected or malformed port, a
                cycle, an unresolved resource, or no workflow output.

        """
        endpoints = {endpoint.node for endpoint in self.endpoints}
        family_ports = self.family_ports().items()

        if self.version != WORKFLOW_VERSION:
            msg = f"unsupported workflow version: {self.version!r}"
            raise InvalidPipelineError(msg)
        elif not self.nodes:
            raise InvalidPipelineError("workflow has no nodes")
        elif missing := endpoints.difference(self.nodes):
            msg = f"references to missing node(s): {sorted(missing)}"
            raise InvalidPipelineError(msg)
        elif fan_in := [port for port, count in family_ports if count > 1]:
            msg = f"multiple stream edges into port(s): {sorted(fan_in)}"
            raise InvalidPipelineError(msg)
        elif mismatches := sorted(self._gen_edge_target_mismatches()):
            msg = f"edge family disagrees with target node: {mismatches}"
            raise InvalidPipelineError(msg)
        elif misdirected := list(self._gen_misdirected_ports()):
            msg = f"port direction does not match its role: {misdirected}"
            raise InvalidPipelineError(msg)
        elif cyclic := list(self.index.cyclic):
            msg = f"edges form a cycle through node(s): {cyclic}"
            raise InvalidPipelineError(msg)
        elif undeclared := sorted(self.referenced_resources.difference(self.resources)):
            msg = f"unresolved resource reference(s): {undeclared}"
            raise InvalidPipelineError(msg)
        elif not self.outputs:
            msg = "workflow exposes no workflow output; declare 'outputs'"
            raise InvalidPipelineError(msg)

    def require_executable(self) -> None:
        """
        Requires a topology the current executor can run.

        Raises:

            InvalidPipelineError: If a source port feeds more than one stream edge.

        """
        family_sources = self.family_sources().items()

        if fan_out := sorted(source for source, count in family_sources if count > 1):
            msg = f"un-supported fan-out from source(s): {fan_out}"
            raise InvalidPipelineError(msg)

    @property
    def isvalid(self) -> bool:
        """Confirms whether the workflow validates."""
        try:
            self.validate()
        except InvalidPipelineError:
            result = False
        else:
            result = True

        return result


_EMPTY_WORKFLOW = Workflow(nodes=[], outputs={}, inputs={})


def _get_node_id(workflow: Workflow, name: str) -> NodeId:
    """Mints a conflict free ``<name>-<occurrence>`` node id."""
    count = len([node for node in workflow.nodes.values() if node.name == name]) + 1
    candidate = f"{name}-{count}"

    while candidate in workflow.nodes:
        count += 1
        candidate = f"{name}-{count}"

    return candidate


def _build_appended_workflow(node: Node, workflow: Workflow | None = None) -> Workflow:
    """Builds a workflow with ``node``s and re-points the default output to it."""
    workflow = _EMPTY_WORKFLOW if workflow is None else workflow

    if (tail := workflow.outputs.get("default")) is None:
        edges = workflow.edges
    else:
        edges = (*workflow.edges, StreamEdge(tail, Endpoint(node.id, "in")))

    return Workflow(
        nodes=[*workflow.nodes.values(), node],
        outputs={**workflow.outputs, "default": Endpoint(node.id, "out")},
        inputs=workflow.inputs,
        edges=edges,
        resources=workflow.resources,
        version=workflow.version,
    )


def _build_chained_workflow(
    name: str,
    workflow: Workflow | None = None,
    *,
    conf: FrozenConf | Conf | None = None,
    options: FrozenOptions | CallOptions | None = None,
    embed: Embed | None = None,
) -> Workflow:
    """Builds a workflow that appends a module node and re-points the default output."""
    workflow = _EMPTY_WORKFLOW if workflow is None else workflow
    node_id = _get_node_id(workflow, name)
    node = ModuleNode(id=node_id, name=name, conf=conf, options=options, embed=embed)
    return _build_appended_workflow(node, workflow)


def _build_write_workflow(
    workflow: Workflow,
    dest: Destination,
    *,
    mode: WriteMode | str = WriteMode.REPLACE,
    fmt: FmtLike | None = None,
    keys: StrLike | None = None,
) -> Workflow:
    """Builds a workflow with a validated write node bound to ``dest``'s backend."""
    prepared = build_write(dest, mode, fmt=fmt, keys=keys)
    location: object = getattr(prepared.target, "dest", None)
    node = WriteNode(
        id=_get_node_id(workflow, "write"),
        name="write",
        backend=prepared.target.backend,
        dest=None if location is None else str(location),
        fmt=prepared.fmt,
        mode=prepared.operation.mode,
        keys=prepared.operation.keys,
    )
    return _build_appended_workflow(node, workflow)


def _require_workflow(value: object, what: str | None = None, **_) -> Workflow:
    if not isinstance(value, Workflow):
        msg = "Pipeline() takes a Workflow or None; use Pipeline.from_module(name) "
        msg += "for a module or Pipeline(source=items) to seed an item stream"
        raise TypeError(msg)

    return value


_optional_workflow = narrow_def_from_require(_require_workflow, default=_EMPTY_WORKFLOW)
_is_context = validator_from_require(
    require_instance, Context, optional=True, error=TypeError
)
_is_settings = validator_from_require(
    require_instance, ExecutionSettings, error=TypeError
)


@define(frozen=True, slots=True)
class PipelineDefinition(Generic[T]):
    """
    An immutable, composable pipeline definition around a ``Workflow``.

    Composition returns the caller's own class; ``Pipeline`` adds running. Build one
    from a ``Workflow``, ``from_module(name)``, ``source=items``, or empty for ``|``.
    A seed is not copied, so a generator is consumed by the first run.

    Attributes:

        workflow: The ``Workflow`` this pipeline runs.

        source: The seed (the items the pipeline starts from), or ``None`` when the
            graph supplies its own.

        context: The environment each run uses, including the resources it provides, or
            ``None`` for a default one.

        settings: How each run executes its per-item work.

    Raises:

        TypeError: If ``context`` is not a ``Context`` or ``settings`` is not an
            ``ExecutionSettings``.

    Examples:

        >>> fetch = PipelineDefinition.from_module("fetch")
        >>> definition = fetch.sort(conf={"combine": "a"})
        >>> sorted(definition.workflow.nodes)
        ['fetch-1', 'sort-1']
        >>> definition.workflow.outputs["default"]
        Endpoint(node='sort-1', port='out')
        >>> PipelineDefinition(source=[{"x": 1}]).source
        [{'x': 1}]

    """

    workflow: Workflow = field(default=_EMPTY_WORKFLOW, converter=_optional_workflow)
    source: SourceLike | None = field(default=None, repr=False)
    context: Context | None = field(
        default=None, kw_only=True, repr=False, validator=_is_context
    )
    settings: ExecutionSettings = field(
        default=DEF_EXECUTION_SETTINGS, kw_only=True, repr=False, validator=_is_settings
    )

    @classmethod
    def from_module(
        cls,
        name: ModuleNameLike,
        *,
        conf: Conf | None = None,
        options: CallOptions | None = None,
        embed: Embed | None = None,
    ) -> Self:
        """
        Builds a pipeline whose sole node is the named module.

        Module existence is not checked here, so a typo surfaces as a
        module-resolution failure when the pipeline runs rather than now.

        Args:

            name: The module's name.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose sole node is the named module.

        Examples:

            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.sort(conf={"combine": "a"})
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='sort-1', port='out')

        """
        workflow = _build_chained_workflow(
            str(name), conf=conf, options=options, embed=embed
        )
        return cls(workflow)

    def _derive(self, workflow: Workflow, source: SourceLike | None) -> Self:
        """Builds a sibling pipeline over a derived workflow and source."""
        return evolve(self, workflow=workflow, source=source)

    def pipe(
        self,
        name: ModuleNameLike,
        *,
        conf: FrozenConf | Conf | None = None,
        options: FrozenOptions | CallOptions | None = None,
        embed: Embed | None = None,
    ) -> Self:
        """
        Chains the next module by name by re-pointing the default output to it.

        Module existence is not checked here, so a typo surfaces as a
        module-resolution failure when the pipeline runs rather than now.

        Args:

            name: The module to append.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose default output is the appended module.

        Examples:

            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.pipe("sort", conf={"combine": "a"})
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='sort-1', port='out')
            >>> delimiter = {"type": "text", "value": " "}
            >>> embed = {"name": "tokenizer", "conf": {"delimiter": delimiter}}
            >>> builder = PipelineDefinition.from_module("itembuilder")
            >>> looped = builder.loop(embed=embed, options={"emit": True})
            >>> looped.workflow.nodes["loop-1"].embed["name"]
            'tokenizer'
            >>> dict(looped.workflow.nodes["loop-1"].options)
            {'emit': True}

        """
        args = str(name), self.workflow
        workflow = _build_chained_workflow(
            *args, conf=conf, options=options, embed=embed
        )
        return self._derive(workflow, self.source)

    def write(
        self,
        dest: Destination | None = None,
        /,
        *,
        mode: WriteMode | str = WriteMode.REPLACE,
        fmt: FmtLike | None = None,
        keys: StrLike | None = None,
        conf: FrozenConf | Conf | None = None,
        options: FrozenOptions | CallOptions | None = None,
        embed: Embed | None = None,
    ) -> Self:
        """
        Appends a write to ``dest``, or chains the ``write`` module without one.

        Given a destination, the new pipeline declares where its items go, how
        they are serialized, and how they reconcile with what is already there.
        Given no destination, the call chains the shipped ``write`` module with
        the module arguments instead, so attribute chaining keeps working.
        Supplying both a destination and module arguments is a call-site error.

        Args:

            dest: The destination path or write target, or ``None`` to chain the
                ``write`` module.

            mode: How the items reconcile with the destination's contents.

            fmt: The serialization format, or ``None`` to derive one.

            keys: The match keys a keyed destination needs.

            conf: The ``write`` module's configuration, if any.

            options: The call options forwarded to the ``write`` module, if any.

            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose default output is the appended node.

        Raises:

            TypeError: If ``dest`` is given together with ``conf``, ``options``,
                or ``embed``.
            ValueError: If ``dest``, ``mode``, ``fmt``, and ``keys`` do not form a
                write the destination supports.

        Examples:

            >>> definition = PipelineDefinition(source=[{"x": 1}]).write("out.csv")
            >>> sorted(definition.workflow.nodes)
            ['write-1']
            >>> definition.workflow.outputs["default"]
            Endpoint(node='write-1', port='out')

        """
        if dest is None:
            written = self.pipe("write", conf=conf, options=options, embed=embed)
        elif conf is not None or options is not None or embed is not None:
            msg = "write() takes either a destination or module arguments, not both"
            raise TypeError(msg)
        else:
            workflow = _build_write_workflow(
                self.workflow, dest, mode=mode, fmt=fmt, keys=keys
            )
            written = self._derive(workflow, self.source)

        return written

    def with_execution(
        self,
        *,
        executor: ExecutorLike | MissingType | None = MISSING,
        concurrency: ConcurrencyLike | MissingType | None = MISSING,
        ordered: bool | MissingType | None = MISSING,
        event_sink: EventSink | MissingType | None = MISSING,
        shutdown_timeout: float | MissingType | None = MISSING,
    ) -> Self:
        """
        Derives a pipeline whose runs execute with the given settings.

        Without settings, a run processes one item at a time in source order. An omitted
        argument keeps the current setting. An explicit ``None`` restores that setting's
        default. Settings are validated here, not when the pipeline runs.

        Args:

            executor: Picks where per-item work runs: ``"auto"``, ``"inline"``,
                ``"thread"``, or ``"process"``. ``None`` selects ``"auto"``.

            concurrency: Max number of items that item-wise modules can work on at once
                across the whole run. ``"auto"`` selects a size based on the machine.
                ``None`` selects sequential processing.

            ordered: Restores result source order. ``None`` selects completion order.

            event_sink: The sink that receives the run's events; ``None`` discards them.

            shutdown_timeout: The bound, in seconds, on teardown under
                asynchronous iteration; ``None`` removes the bound.

        Returns:

            A new pipeline carrying the updated settings.

        Raises:

            ValueError: If ``executor`` names no known executor, ``concurrency``
                is below one, or ``shutdown_timeout`` is negative or NaN.

            TypeError: If ``concurrency``, ``ordered``, or ``shutdown_timeout``
                has the wrong type.

        Examples:

            >>> base = PipelineDefinition.from_module("fetch")
            >>> threaded = base.with_execution(executor="thread", concurrency=4)
            >>> threaded.settings.executor.value, threaded.settings.concurrency
            ('thread', 4)
            >>> threaded.with_execution(ordered=True).settings.concurrency
            4
            >>> print(threaded.with_execution(concurrency=None).settings.concurrency)
            None
            >>> print(base.settings.concurrency)
            None

        """
        requested = {
            "executor": executor,
            "concurrency": concurrency,
            "ordered": ordered,
            "event_sink": event_sink,
            "shutdown_timeout": shutdown_timeout,
        }
        defaults = fields(ExecutionSettings)
        changes = {
            name: getattr(defaults, name).default if value is None else value
            for name, value in requested.items()
            if value is not MISSING
        }
        return evolve(self, settings=evolve(self.settings, **changes))

    def with_context(self, context: Context) -> Self:
        """
        Derives a pipeline whose runs use ``context``.

        The context supplies the run's input values, mode, and resources, and
        replaces any context this pipeline already carries.

        Args:

            context: The environment each run uses.

        Returns:

            A new pipeline bound to ``context``; this one is unchanged.

        Examples:

            >>> from riko import Context
            >>>
            >>> context = Context(inputs={"limit": 5})
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.with_context(context)
            >>> definition.context is context
            True

        """
        return evolve(self, context=context)

    @overload
    def with_resource[R](  # noqa: E704
        self,
        name: str,
        definition: LifecycleFactory[R],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    @overload  # noqa: E301
    def with_resource[R](  # noqa: E704
        self,
        name: str,
        definition: ReusableResource[R],
        *,
        credential: None = ...,
        lazy: Literal[False] = ...,
    ) -> Self: ...
    def with_resource[R](  # noqa: E301
        self,
        name: str,
        definition: ResourceDefinition[R],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> Self:
        """
        Derives a pipeline whose runs provide a resource ``definition`` as ``name``.

        The resource is added to this pipeline's context, or to a default context
        when it has none, exactly as ``Context.with_resource`` provides it. A
        factory is entered by the run rather than here, so ``credential``/``lazy``
        apply only to a factory.

        Args:

            name: The Context name the resource is provided under.
            definition: A ``Resource``/``LifecycleFactory`` that wraps a resource value.
            credential: A credential reference for a factory.
            lazy: Whether entry should defer until first use. Not yet honored: a run
                acquires every resource its nodes bind, whether or not it is used.

        Returns:

            A new pipeline whose context carries the resource. This one is unchanged.

        Raises:

            TypeError: When ``credential``/``lazy`` accompany a ``Resource`` (they
                belong on a ``LifecycleFactory``).

        Examples:

            >>> def open_db():
            ...     yield {"rows": []}
            >>>
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> definition = fetch.with_resource("db", open_db)
            >>> sorted(definition.context.resources)
            ['db']

        """
        base = Context() if self.context is None else self.context
        bound = base.with_resource(name, definition, credential=credential, lazy=lazy)
        return evolve(self, context=bound)

    @classmethod
    def subscribe(cls, *args: object, **kwargs: object) -> Self:
        """
        Reserves the local-subscription constructor; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; local subscriptions are not available yet.

        """
        raise NotImplementedError("local subscriptions are not available yet")

    def publish(self, *args: object, **kwargs: object) -> Self:
        """
        Reserves publishing to a subscription; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; publishing is not available yet.

        """
        raise NotImplementedError("publishing to a subscription is not available yet")

    def split(self, *args: object, **kwargs: object) -> tuple[Self, ...]:
        """
        Reserves streaming fan-out into branches; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; streaming fan-out is not available yet.

        """
        raise NotImplementedError("streaming fan-out is not available yet")

    def map(self, *args: object, **kwargs: object) -> Self:
        """
        Reserves chaining a callable as its own node; its arguments are not settled.

        Args:

            args: The not-yet-settled positional arguments.
            kwargs: The not-yet-settled keyword arguments.

        Raises:

            NotImplementedError: Always; callable nodes are not available yet.

        """
        raise NotImplementedError("chaining a callable as a node is not available yet")

    def __getattr__(self, name: str) -> Callable[..., Self]:
        """
        Chains a module by attribute. E.g., ``.sort()`` appends the sort module.

        A module named like an existing ``Pipeline`` method (e.g., ``split``) needs to
        use ``.pipe(name)``, since the method wins. Any other non-underscore attribute
        is treated as a module name. This means a typo surfaces as a module-resolution
        failure rather than ``AttributeError``. Mapping names are excluded to keep a
        pipeline from looking dict-like to duck-typed callers.
        """
        if name.startswith("_") or name in {"keys", "values", "items", "get"}:
            raise AttributeError(name)

        return partial(self.pipe, name)

    def _or_template(self, other: PipelineDefinition) -> Self:
        """Chains a single-module, source-less pipeline used as a reusable template."""
        nodes = other.workflow.nodes.values()
        node = next(iter(nodes)) if len(nodes) == 1 else None

        if other.source is None and isinstance(node, ModuleNode):
            chained = self.pipe(
                node.name, conf=node.conf, options=node.options, embed=node.embed
            )
        else:
            msg = "pipeline template must define exactly one module"
            raise InvalidPipelineError(msg)

        return chained

    def __or__(self, other: object) -> Self:
        """
        Chains a module name, config pair, or single-module template using ``|``.

        Args:

            other: A module name, a ``(name, conf)`` pair, or a one-module pipeline.

        Returns:

            A new pipeline with the module appended.

        Examples:

            >>> definition = PipelineDefinition.from_module("fetch") | "sort"
            >>> sorted(definition.workflow.nodes)
            ['fetch-1', 'sort-1']
            >>> fetch = PipelineDefinition.from_module("fetch")
            >>> configured = fetch | ("sort", {"combine": "a"})
            >>> dict(configured.workflow.nodes["sort-1"].conf)
            {'combine': 'a'}

        """
        if isinstance(other, str):
            chained = self.pipe(other)
        elif _is_module_pair(other):
            name, conf = other
            chained = self.pipe(name, conf=conf)
        elif isinstance(other, PipelineDefinition):
            chained = self._or_template(other)
        else:
            chained = cast("Self", NotImplemented)

        return chained

    def __ror__(self, other: object) -> Self:
        """
        Seeds the pipeline with the items on the left of ``|``.

        Args:

            other: The item stream, async item stream, or awaitable to seed this
                pipeline with.

        Returns:

            A new pipeline seeded with ``other``.

        Examples:

            >>> items = [{"x": 1}, {"x": 2}]
            >>> definition = items | PipelineDefinition.from_module("sort")
            >>> definition.source is items
            True

        """
        if self.source is None and _is_source(other):
            primed = self._derive(self.workflow, other)
        else:
            primed = cast("Self", NotImplemented)

        return primed


__all__ = [
    "ActionNode",
    "CacheNode",
    "ModuleNode",
    "Node",
    "PipelineDefinition",
    "PublishEdge",
    "ReadNode",
    "StreamEdge",
    "SubscribeNode",
    "Workflow",
    "WriteNode",
]
