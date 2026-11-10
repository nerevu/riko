# vim: sw=4:ts=4:expandtab
"""
The immutable ``Workflow`` graph model, with its loaders and serializers.

A ``Workflow`` holds the nodes, edges, outputs, input schemas, and declared
resources of one graph. It is the structural immutable definition that wraps the
nodes and edges, checks graph validity on request, and reads itself from, and writes
itself to, a workflow document (``WorkflowDocument``).

Examples:

    Basic usage::

        >>> from riko import Endpoint, Workflow
        >>> from riko.ext import ModuleNode
        >>>
        >>> flow = Workflow(
        ...     nodes=[ModuleNode(id="fetch-1", name="fetch")],
        ...     outputs={"default": Endpoint("fetch-1", "out")},
        ... )
        >>> flow
        Workflow(fetch-1; outputs: default)
        >>> Workflow.parse(flow.serialize()) == flow
        True

"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from functools import cached_property, partial
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Self

from attrs import define, evolve, field

from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_values
from riko.base._guards import is_mapping, require_listlike, require_mapping
from riko.base._iterutils import sort_stably, unique_everseen
from riko.base._require_guards import normalize_strs, require_instances, require_str
from riko.base._typing import resolve_enum
from riko.types._enums import DocumentShape
from riko.types._frozendict import (
    EMPTY_INPUT_SCHEMAS,
    FrozenDict,
    FrozenInputSchemas,
    FrozenNodes,
    FrozenOutputs,
    FrozenResources,
    FrozenWorkflowEdges,
    freeze,
    instances_freezer,
    json_freeze,
    mapping_converter,
)
from riko.types._pipedef import Embed, PipeDag
from riko.types._workflow import (
    WORKFLOW_VERSION,
    Endpoint,
    NodeId,
    PortEdge,
    RawEdge,
    RawEndpoint,
    RawNode,
    RawWorkflow,
    WorkflowEdge,
    WorkflowIndex,
    parse_port,
)

from ._inputs import compile_input_schema
from ._nodes import (
    CallableNode,
    ModuleNode,
    RikoNode,
    RunnableNode,
    StreamEdge,
    SubscribeNode,
    get_family_edges,
)
from ._normalize import (
    build_nodes,
    build_raw_workflow,
    get_free_occurrence,
    normalize_edge,
    normalize_input_schemas,
    normalize_outputs,
    require_raw_workflow,
)
from ._serialize import parse_document, serialize_workflow

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._enums import DocumentShapeLike
    from riko.types._frozendict import FrozenPortEdges, JSONValue
    from riko.types._io import PathLike
    from riko.types._pipedef import PipeDefLike
    from riko.types._workflow import EdgeFamily, WorkflowDocument

type WorkflowLike = Workflow | RawWorkflow | Mapping[str, object]
type DocumentMapping = RawWorkflow | PipeDefLike | PipeDag
type DocumentLike = str | WorkflowDocument | Workflow | DocumentMapping
type RawNodes = Sequence[RawNode] | Mapping[str, RawNode]
type NodeLike = RikoNode | RawNode | Mapping[str, object]
type NodesLike = Sequence[NodeLike] | Mapping[str, NodeLike]
type EndpointLike = Endpoint | RawEndpoint | Mapping[str, object]
type EdgeLike = PortEdge | RawEdge | Mapping[str, object]
type RikoNodeCollection = Mapping[NodeId, RikoNode]
type RikoNodes = Sequence[RikoNode]
type PortEdges = Sequence[PortEdge]
type RawPortEdges = Sequence[RawEdge]
type RawInputs = Mapping[str, object]
type Inputs = Mapping[str, JSONValue]
type RawOutputs = Mapping[str, RawEndpoint]
type Outputs = Mapping[str, Endpoint]
type OutputsLike = Mapping[str, EndpointLike]
type InputSchema = Mapping[str, JSONValue]
type RawInputSchema = str | Mapping[str, object]
type InputSchemaLike = InputSchema | RawInputSchema
type InputSchemas = Mapping[str, InputSchema]
type RawInputSchemas = Mapping[str, RawInputSchema]
type InputSchemasLike = InputSchemas | RawInputSchemas

_EMPTY_OUTPUTS: FrozenOutputs = FrozenDict()
_EMPTY_NODES: FrozenNodes = FrozenDict()
_EMPTY_EDGES: FrozenPortEdges = ()
_EMPTY_RESOURCES: FrozenResources = ()

endpoint_freezer = instances_freezer(Endpoint, "Workflow output")
outputs_converter = mapping_converter(
    endpoint_freezer, Outputs, what="Workflow 'outputs'"
)

resource_names_converter = partial(
    normalize_strs, what="Workflow 'resources'", strict=True
)


def _input_schemas_freezer(value: InputSchemasLike) -> FrozenInputSchemas:
    """Requires every input's schema to be a mapping and freezes it."""
    what = "Workflow 'input_schemas'"
    schemas = {k: require_mapping(v, f"{what} {k!r}") for k, v in value.items()}
    return freeze(schemas, mapping_value_func=json_freeze)


input_schemas_converter = mapping_converter(
    _input_schemas_freezer, InputSchemasLike, what="Workflow 'input_schemas'"
)


def _edges_converter(value: PortEdges) -> FrozenPortEdges:
    """Requires every workflow edge to be a ``PortEdge``."""
    edges = require_listlike(value, "Workflow 'edges'")
    return tuple(require_instances(PortEdge, edges, "Workflow edge"))


def _require_keyed_nodes(value: RikoNodeCollection, what: str) -> RikoNodeCollection:
    """Requires ``value`` to hold nodes keyed by their own ids, as a ``Workflow``'s."""
    items = value.items()

    if not all(isinstance(node, RikoNode) and node.id == key for key, node in items):
        raise InvalidPipelineError(f"{what} must be a list")

    return value


def nodes_converter(value: RikoNodes | RikoNodeCollection) -> FrozenNodes:
    """
    Keys each workflow node by its id and rejects mappings or repeated ids.

    The id-keyed nodes of another ``Workflow`` pass through, so ``evolve`` keeps them.
    """
    if is_mapping(value):
        result = _require_keyed_nodes(value, "Workflow 'nodes'")
    else:
        _nodes = require_listlike(value, "Workflow 'nodes'")
        nodes = list(require_instances(RikoNode, _nodes, "Workflow node"))
        result = {node.id: node for node in nodes}

        if len(result) < len(nodes):
            raise InvalidPipelineError("Workflow 'nodes' must not repeat a node id")

    return freeze(result)


@define(frozen=True, slots=True, repr=False)
class Workflow:
    """
    The strict in-memory workflow graph: nodes, edges, outputs, and input schemas.

    Cross-field graph validity is checked explicitly by ``validate()``. ``parse()`` and
    ``load()`` read a workflow from any readable workflow input. ``serialize()`` writes
    it back out as a workflow document.

    Attributes:

        nodes: The graph nodes (given as an iterable and stored keyed by node id).
        module_nodes: The nodes that run a module, keyed by node id.
        callable_nodes: The nodes that run a callable, keyed by node id.
        runnable_nodes: The nodes that run a module or a callable, keyed by node id.
        embeds: The module name and conf each loop node runs per item, keyed by node id.
        index: The graph index derived from the nodes, edges, and outputs.
        edges: The stream and publish edges, in listing order.
        outputs: The workflow outputs: named endpoints the workflow exposes.

        input_schemas: Each input's schema (a JSON Schema), keyed by input name. Node
            configuration refers to an input with an ``{"input": name}`` mapping.

        resources: The workflow declared resources (must include each one a node binds).
        version: The workflow format version.

    Examples:

        >>> from riko.ext import ModuleNode
        >>>
        >>> flow = Workflow(
        ...     nodes=[ModuleNode(id="fetch-1", name="fetch")],
        ...     outputs={"default": Endpoint("fetch-1", "out")},
        ...     resources="db",
        ... )
        >>> flow.resources
        ('db',)
        >>> flow.is_valid
        True

    """

    nodes: FrozenNodes = field(default=_EMPTY_NODES, converter=nodes_converter)
    outputs: FrozenOutputs = field(default=_EMPTY_OUTPUTS, converter=outputs_converter)
    input_schemas: FrozenInputSchemas = field(
        default=EMPTY_INPUT_SCHEMAS, converter=input_schemas_converter
    )
    edges: FrozenPortEdges = field(default=_EMPTY_EDGES, converter=_edges_converter)
    resources: FrozenResources = field(
        default=_EMPTY_RESOURCES, converter=resource_names_converter
    )
    version: str = WORKFLOW_VERSION

    @classmethod
    def from_raw(cls, value: WorkflowLike) -> Self:
        """
        Builds a ``Workflow`` from any workflow mapping (``WorkflowLike``).

        This is the one structural normalization boundary. Listed nodes get
        ``<name>-<occurrence>`` ids, legacy port names become the canonical grammar,
        omitted outputs default to the lone leaf node, and string input's schemas become
        full JSON Schemas. The result is not validated. Call ``validate()`` or
        ``parse()`` for that.

        Args:

            value: A mapping with ``nodes`` and optional ``edges``, ``outputs``,
                ``input_schemas``, ``resources``, and ``version``.

        Returns:

            The normalized ``Workflow``.

        Raises:

            InvalidPipelineError: If ``value`` is not a mapping or its structure is
                malformed, or a ``Workflow`` has a callable node (a Python callable has
                no workflow document form).

        Examples:

            >>> from riko import Workflow
            >>>
            >>> flow = Workflow.from_raw({"nodes": [{"name": "fetch"}]})
            >>> flow
            Workflow(fetch-1; outputs: default)
            >>> flow.nodes["fetch-1"].name
            'fetch'

        """
        loose = build_raw_workflow(value) if isinstance(value, Workflow) else value
        raw = require_raw_workflow(require_mapping(loose, "workflow"))
        nodes = build_nodes(raw.get("nodes", ()))
        _edges = require_listlike(raw.get("edges", ()), "edges")
        edges = [normalize_edge(require_mapping(e, "edge"), **nodes) for e in _edges]
        version = raw.get("version", WORKFLOW_VERSION)

        return cls(
            nodes=nodes,
            outputs=normalize_outputs(raw.get("outputs"), edges, *nodes),
            input_schemas=normalize_input_schemas(raw.get("input_schemas")),
            edges=edges,
            resources=normalize_strs(raw.get("resources"), "Workflow 'resources'"),
            version=require_str(version, "workflow 'version'"),
        )

    @classmethod
    def parse(
        cls, document: DocumentLike, *, shape: DocumentShapeLike | None = None
    ) -> Self:
        """
        Parses a workflow input of any readable shape into a validated ``Workflow``.

        Recognizes workflow documents, pipe definitions (``PipeDef``), and ``PipeDag``s
        from their structure. Accepts text, bytes, or a parsed mapping.

        Args:

            document: The workflow input:

                - ``WorkflowDocument``: Mapping containing ``nodes`` or ``version``

                - ``PipeDef``: Mapping containing ``modules`` and either ``src``/``tgt``
                  ``wires``, an ``output`` module, or a ``PipeDef``-only module key

                - ``PipeDag``: Mapping containing ``modules`` and either ``wires``
                  written as lists or a ``PipeDag``-only module key

                - ``Workflow``: Re-normalized to an equivalent ``Workflow``

                A mapping containing ``modules`` with none of these markers is a
                ``PipeDef`` when it has at least one module and every module has a
                ``type``, ``id``, and ``conf``; and a ``PipeDag`` otherwise.

        Kwargs:

            shape: The shape to read it as (``"dag"``, ``"v1"``, or ``"v2"``). Omit it
                to detect the shape from the input. A ``Workflow`` reads only as
                ``"v2"``.

        Returns:

            The validated ``Workflow``.

        Raises:

            InvalidPipelineError: If ``document`` is neither valid JSON nor a mapping,
                its shape cannot be detected, it does not hold the shape it is read as,
                a module or wire is malformed, a key has no ``Workflow`` equivalent, two
                configuration keys differ only in case, two ``input`` modules give an
                input different schemas, a ``Workflow`` has a callable node (a Python
                callable has no workflow document form), or the resulting workflow is
                invalid.

        Examples:

            >>> from riko import Workflow
            >>>
            >>> flow = Workflow.parse('{"nodes": [{"name": "fetch"}]}')
            >>> flow
            Workflow(fetch-1; outputs: default)
            >>> Workflow.parse(flow.serialize()) == flow
            True
            >>> dag = {"modules": [{"name": "forever"}, {"name": "truncate"}]}
            >>> Workflow.parse(dag, shape="dag")
            Workflow(sw-1 -> sw-2; outputs: default)
            >>> Workflow.parse("[]")
            Traceback (most recent call last):
            ...
            riko.base.exceptions.InvalidPipelineError: ...document must be a mapping...

        """
        resolved = resolve_enum(DocumentShape, shape, "shape", strict=False)

        if not isinstance(document, Workflow):
            raw = parse_document(document, shape=resolved)
        elif resolved is None or resolved is DocumentShape.V2:
            raw = build_raw_workflow(document)
        else:
            msg = f"a Workflow can only be read as shape 'v2', not {resolved.value!r}"
            raise InvalidPipelineError(msg)

        flow = cls.from_raw(raw)
        flow.validate()
        return flow

    @classmethod
    def load(cls, path: PathLike, *, shape: DocumentShapeLike | None = None) -> Self:
        """
        Loads a validated ``Workflow`` from a JSON file of any readable shape.

        Args:

            path: The file to read.

        Kwargs:

            shape: The shape to read it as. Omit it to detect the shape from the file.

        Returns:

            The validated ``Workflow``.

        Raises:

            OSError: If the file cannot be read.
            InvalidPipelineError: If the file does not hold a valid workflow input.

        Examples:

            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> from riko import Workflow
            >>>
            >>> flow = Workflow.parse({"nodes": [{"name": "fetch"}]})
            >>>
            >>> with TemporaryDirectory() as tmp:
            ...     path = Path(tmp) / "flow.json"
            ...     _ = path.write_bytes(flow.serialize())
            ...     Workflow.load(path) == flow
            True

        """
        return cls.parse(Path(path).read_bytes(), shape=shape)

    def serialize(self, *, indent: int | None = 4) -> WorkflowDocument:
        """
        Serializes the workflow into a byte-stable ``WorkflowDocument``.

        Map keys are sorted at every level and node/edge fields use a fixed shape, so
        the same workflow always yields identical bytes. Edge order follows the
        workflow. The default is the readable indented form committed files are
        stored in.

        Kwargs:

            indent: Number of spaces to indent each nesting level by. Pass ``None`` for
                the compact single-line form.

        Returns:

            The ``WorkflowDocument`` as UTF-8 JSON bytes.

        Examples:

            >>> from riko import Workflow
            >>>
            >>> flow = Workflow.parse({"nodes": [{"name": "fetch"}]})
            >>> flow.serialize().decode("utf-8").splitlines()[1]
            '    "edges": [],'

        """
        return serialize_workflow(self, indent=indent)

    def _is_chain(self) -> bool:
        """Reports whether the nodes form one unbranched, acyclic line."""
        index = self.index
        upstream, downstream = index.upstream, index.downstream

        return (
            len(self.nodes) > 0
            and not index.cyclic
            and len(index.order) == len(self.nodes)
            and len(index.roots) == 1
            and all(len(upstream.get(node_id, ())) <= 1 for node_id in self.nodes)
            and all(len(downstream.get(node_id, ())) <= 1 for node_id in self.nodes)
        )

    @property
    def summary(self) -> str:
        """Describes the graph in one line: its chain or its size, and its outputs."""
        if self.is_empty:
            result = "empty"
        else:
            if self._is_chain():
                topology = " -> ".join(self.index.order)
            else:
                topology = f"nodes: {len(self.nodes)}, edges: {len(self.edges)}"

            outputs = f"; outputs: {', '.join(self.outputs)}" if self.outputs else ""
            result = f"{topology}{outputs}"

        return result

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.summary})"

    def get_family_sources(
        self, family: EdgeFamily = "stream"
    ) -> Counter[tuple[str, str]]:
        """
        Gets how many ``family`` edges each ``(node, port)`` source feeds.

        Equivalent spellings, e.g., ``out:1`` and ``out:01``, count as the same port.
        """
        edges = get_family_edges(self.edges, family)
        return Counter(edge.source.port_key for edge in edges)

    def get_family_ports(
        self, family: EdgeFamily = "stream"
    ) -> Counter[tuple[str, str]]:
        """
        Gets how many ``family`` edges each ``(node, port)`` target receives.

        Equivalent spellings, e.g., ``in:1`` and ``in:01``, count as the same port.
        """
        edges = get_family_edges(self.edges, family)
        return Counter(edge.target.port_key for edge in edges)

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
    def graph_edges(self) -> FrozenWorkflowEdges:
        """Flattens each edge into the node-and-port record the graph index reads."""
        return tuple(
            WorkflowEdge(e.source.node, e.target.node, e.source.port, e.target.port)
            for e in self.edges
        )

    @cached_property
    def module_nodes(self) -> FrozenDict[NodeId, ModuleNode]:
        """The nodes that run a module, keyed by node id."""
        nodes = {k: n for k, n in self.nodes.items() if isinstance(n, ModuleNode)}
        return FrozenDict.from_frozen(nodes)

    @cached_property
    def callable_nodes(self) -> FrozenDict[NodeId, CallableNode[object]]:
        """The nodes that run a callable, keyed by node id."""
        nodes = {k: n for k, n in self.nodes.items() if isinstance(n, CallableNode)}
        return FrozenDict.from_frozen(nodes)

    @cached_property
    def runnable_nodes(self) -> FrozenDict[NodeId, RunnableNode]:
        """The nodes that run a module or a callable, keyed by node id."""
        return FrozenDict.from_frozen({**self.module_nodes, **self.callable_nodes})

    @cached_property
    def embeds(self) -> FrozenDict[NodeId, Embed]:
        """The embed (module name and conf) each loop node runs per item, by node id."""
        nodes = self.module_nodes.items()
        embeds = {k: n.embed for k, n in nodes if n.embed is not None}
        return FrozenDict.from_frozen(embeds)

    @cached_property
    def dependencies(self) -> tuple[str, ...]:
        """The module and stored-workflow names the nodes and their loop embeds run."""
        names = (node.name for node in self.module_nodes.values())
        embeds = (embed["name"] for embed in self.embeds.values())
        return sort_stably({*names, *embeds})

    @cached_property
    def index(self) -> WorkflowIndex:
        """Interprets the topology once; edges and outputs name declared nodes."""
        return WorkflowIndex(self.nodes, self.graph_edges, self.outputs)

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

    @property
    def referenced_inputs(self) -> set[str]:
        """Collects the input names the workflow's node configurations refer to."""
        nodes = self.nodes.values()
        return set(chain.from_iterable(node.referenced_inputs for node in nodes))

    def get_node_id(self, name: str) -> NodeId:
        """
        Gets a ``<name>-<occurrence>`` node id that no node in the workflow uses yet.

        Args:

            name: The node name the id is based on.

        Returns:

            The lowest-numbered free id a node would get in a normalized workflow.

        Examples:

            >>> from riko.ext import ModuleNode
            >>>
            >>> flow = Workflow(nodes=[ModuleNode(id="fetch-1", name="fetch")])
            >>> flow.get_node_id("fetch"), flow.get_node_id("sort")
            ('fetch-2', 'sort-1')

        """
        return f"{name}-{get_free_occurrence(name, self.nodes)}"

    def _require_default_output(self, what: str) -> Endpoint | None:
        """Requires a default output to chain through, unless the workflow is empty."""
        if (default := self.outputs.get("default")) is None and self.nodes:
            msg = f"{what} has nodes but no default output. Build it with "
            msg += "Workflow().with_node(node), or declare "
            msg += "outputs={'default': Endpoint(id, 'out')}"
            raise InvalidPipelineError(msg)

        return default

    def with_node(self, node: RikoNode) -> Self:
        """
        Builds a workflow with ``node`` appended as its default output.

        The previous default output streams into ``node``, and the workflow appends any
        new resources the ``node`` binds at the end.

        Args:

            node: The node to append.

        Returns:

            A new workflow whose default output is ``node``'s output.

        Raises:

            InvalidPipelineError: If the workflow has nodes but no default output to
                append after.

        Examples:

            >>> from riko.ext import ModuleNode
            >>>
            >>> fetch = ModuleNode(id="fetch-1", name="fetch")
            >>> sort = ModuleNode(id="sort-1", name="sort", resources="db")
            >>> flow = Workflow().with_node(fetch).with_node(sort)
            >>> flow.summary
            'fetch-1 -> sort-1; outputs: default'
            >>> flow.resources
            ('db',)

        """
        if (tail := self._require_default_output("this workflow")) is None:
            edges = self.edges
        else:
            edges = (*self.edges, StreamEdge(tail, Endpoint(node.id, "in")))

        return evolve(
            self,
            nodes=[*self.nodes.values(), node],
            outputs={**self.outputs, "default": Endpoint(node.id, "out")},
            edges=edges,
            resources=unique_everseen(chain(self.resources, node.resources.values())),
        )

    def _get_free_ids(self, other: Workflow) -> dict[NodeId, NodeId]:
        """Gets an id for each of ``other``'s nodes that no node here uses yet."""
        taken = set(self.nodes)
        free_ids: dict[NodeId, NodeId] = {}

        for node_id in other.nodes:
            base, _, occurrence = node_id.rpartition("-")
            name = base if base and occurrence.isdigit() else node_id

            if node_id in taken:
                free_ids[node_id] = f"{name}-{get_free_occurrence(name, taken)}"
            else:
                free_ids[node_id] = node_id

            taken.add(free_ids[node_id])

        return free_ids

    def with_workflow(self, other: Workflow) -> Self:
        """
        Builds a workflow with ``other`` appended after its default output.

        The previous default output streams into ``other``'s open default input port.
        ``other``'s workflow outputs replace existing ones of the same name. In case of
        duplicate node ids, ``other``'s nodes are renamed to the next free
        ``<name>-<occurrence>``.

        Args:

            other: The workflow to append.

        Returns:

            A new workflow whose default output is ``other``'s default output.

        Raises:

            InvalidPipelineError: If either workflow has nodes but no default output;
                ``other`` doesn't have exactly one node with an open default input port;
                both define the same non-default workflow output; or both give the same
                input different schemas.

        Examples:

            >>> from riko.ext import ModuleNode
            >>>
            >>> node = ModuleNode(id="fetch-1", name="fetch")
            >>> fetch = Workflow().with_node(node)
            >>> sort = Workflow().with_node(ModuleNode(id="sort-1", name="sort"))
            >>> fetch.with_workflow(sort.with_node(node)).summary
            'fetch-1 -> sort-1 -> fetch-2; outputs: default'

        """
        free_ids = self._get_free_ids(other)

        def move(endpoint: Endpoint) -> Endpoint:
            return Endpoint(free_ids[endpoint.node], endpoint.port)

        outputs = map_values(move, other.outputs)
        index = other.index
        heads = [free_ids[node_id] for node_id in index.order if index.is_open(node_id)]
        tail = self._require_default_output("this workflow")
        other._require_default_output("the appended workflow")
        schemas = other.input_schemas

        if tail is not None and other.nodes and len(heads) != 1:
            msg = "an appended workflow needs exactly one node with an open input, "
            msg += f"not {len(heads)}: {heads}"
            raise InvalidPipelineError(msg)
        elif named := (set(self.outputs).intersection(outputs)) - {"default"}:
            msg = f"both workflows define workflow output(s): {sorted(named)}"
            raise InvalidPipelineError(msg)
        elif clashing := [
            k for k, v in schemas.items() if self.input_schemas.get(k, v) != v
        ]:
            msg = f"both workflows give input(s) different schemas: {sorted(clashing)}"
            raise InvalidPipelineError(msg)
        elif tail is None or not other.nodes:
            wiring = []
        else:
            wiring = [StreamEdge(tail, Endpoint(heads[0], "in"))]

        nodes = [evolve(node, id=free_ids[node.id]) for node in other.nodes.values()]
        edges = [
            evolve(edge, source=move(edge.source), target=move(edge.target))
            for edge in other.edges
        ]

        return evolve(
            self,
            nodes=[*self.nodes.values(), *nodes],
            outputs={**self.outputs, **outputs},
            input_schemas={**self.input_schemas, **schemas},
            edges=[*self.edges, *wiring, *edges],
            resources=unique_everseen(chain(self.resources, other.resources)),
        )

    def validate_input_schemas(self) -> None:
        """
        Validates the schema of each workflow input.

        Each input's schema must be a JSON Schema whose ``type``, when present, names
        JSON types. ``validate`` runs this along with the graph checks.

        Raises:

            InvalidPipelineError: If an input's schema is not a valid JSON Schema.

        Examples:

            >>> integer = Workflow(input_schemas={"limit": {"type": "integer"}})
            >>> integer.validate_input_schemas()
            >>> misspelled = Workflow(input_schemas={"q": {"type": "strng"}})
            >>> misspelled.validate_input_schemas()
            Traceback (most recent call last):
            ...
            riko.base.exceptions.InvalidPipelineError: ...'q' has an invalid schema: ...

        """
        for name, schema in self.input_schemas.items():
            compile_input_schema(name, schema)

    def validate(self) -> None:
        """
        Validates workflow graph structure, references, and input schemas.

        Raises:

            InvalidPipelineError: If the graph has an unsupported version, an empty node
                set, a dangling edge or output reference, more than one stream edge into
                a port, a publish/subscribe edge mismatch, a misdirected or malformed
                port, a cycle, an unresolved resource, a reference to an input with no
                schema, an invalid input schema, or no workflow output.

        """
        self.validate_input_schemas()
        endpoints = {endpoint.node for endpoint in self.endpoints}
        inputs = self.referenced_inputs

        if self.version != WORKFLOW_VERSION:
            msg = f"unsupported workflow version: {self.version!r}"
            raise InvalidPipelineError(msg)
        elif not self.nodes:
            raise InvalidPipelineError("workflow has no nodes")
        elif missing := endpoints.difference(self.nodes):
            msg = f"references to missing node(s): {sorted(missing)}"
            raise InvalidPipelineError(msg)
        elif misdirected := list(self._gen_misdirected_ports()):
            msg = f"port direction does not match its role: {misdirected}"
            raise InvalidPipelineError(msg)
        elif fan_in := [p for p, count in self.get_family_ports().items() if count > 1]:
            msg = f"multiple stream edges into port(s): {sorted(fan_in)}"
            raise InvalidPipelineError(msg)
        elif mismatches := sorted(self._gen_edge_target_mismatches()):
            msg = f"edge family disagrees with target node: {mismatches}"
            raise InvalidPipelineError(msg)
        elif cyclic := list(self.index.cyclic):
            msg = f"edges form a cycle through node(s): {cyclic}"
            raise InvalidPipelineError(msg)
        elif undeclared := sorted(self.referenced_resources.difference(self.resources)):
            msg = f"unresolved resource reference(s): {undeclared}"
            raise InvalidPipelineError(msg)
        elif unresolved := sorted(inputs.difference(self.input_schemas)):
            raise InvalidPipelineError(f"unresolved input reference(s): {unresolved}")
        elif not self.outputs:
            msg = "workflow exposes no workflow output; declare 'outputs'"
            raise InvalidPipelineError(msg)

    def validate_document_nodes(self) -> None:
        """
        Validates that every node can be written to a workflow document.

        Raises:

            InvalidPipelineError: If a node is a callable node.

        Examples:

            >>> from riko.ext import CallableNode, ModuleNode
            >>>
            >>> flow = Workflow().with_node(ModuleNode(id="a", name="hash"))
            >>> flow.validate_document_nodes()
            >>> node = CallableNode(id="len-1", name="len", fn=len)
            >>> flow.with_node(node).validate_document_nodes()
            Traceback (most recent call last):
                ...
            riko.base.exceptions.InvalidPipelineError: ...callable node(s) ['len-1']...

        """
        if callables := sorted(self.callable_nodes):
            msg = "a Python callable has no workflow document form"
            raise InvalidPipelineError(f"callable node(s) {callables}: {msg}")

    def require_executable(self) -> None:
        """
        Requires a topology the current executor can run.

        Raises:

            InvalidPipelineError: If a source port feeds more than one stream edge.

        """
        family_sources = self.get_family_sources().items()

        if fan_out := sorted(source for source, count in family_sources if count > 1):
            msg = f"un-supported fan-out from source(s): {fan_out}"
            raise InvalidPipelineError(msg)

    def require_runnable_only(self, what: str) -> None:
        """
        Requires every node to run a module or a callable.

        Activities such as execution support no other node family.

        Args:

            what: The activity that needs runnable nodes, e.g. ``"execution"``.

        Raises:

            InvalidPipelineError: If a node belongs to another family.

        Examples:

            >>> from riko.ext import ModuleNode
            >>>
            >>> flow = Workflow(
            ...     nodes=[ModuleNode(id="a", name="hash")],
            ...     outputs={"default": Endpoint("a", "out")},
            ... )
            >>> flow.require_runnable_only("execution")

        """
        supported = self.runnable_nodes
        nodes = (node for key, node in self.nodes.items() if key not in supported)

        if stray := sorted({node.family for node in nodes}):
            msg = f"{', '.join(stray)} node {what} is not yet supported"
            raise InvalidPipelineError(msg)

    @property
    def is_valid(self) -> bool:
        """Confirms whether the workflow validates."""
        try:
            self.validate()
        except InvalidPipelineError:
            result = False
        else:
            result = True

        return result


__all__ = ["Workflow"]
