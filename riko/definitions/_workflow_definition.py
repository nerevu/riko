# vim: sw=4:ts=4:expandtab
"""
The immutable ``Workflow`` graph model, with its loaders and serializers.

A ``Workflow`` holds the nodes, edges, outputs, input declarations, and declared
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
from collections.abc import Iterable, Mapping
from functools import cached_property, partial
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Self

from attrs import define, evolve, field

from riko.base._exceptions import InvalidPipelineError
from riko.base._guards import require_sequence
from riko.base._iterutils import map_values, unique_everseen
from riko.base._require_guards import normalize_strs, require_instances
from riko.base._typing import resolve_enum
from riko.types._enums import DocumentShape
from riko.types._frozendict import (
    FrozenDict,
    FrozenJSON,
    freeze_json,
    instances_freezer,
    mapping_converter,
)
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

from ._migrate import migrate_pipe_def
from ._nodes import (
    CallableNode,
    ModuleNode,
    Node,
    RunnableNode,
    StreamEdge,
    SubscribeNode,
    get_family_edges,
)
from ._normalize import build_raw_graph, build_workflow_fields, get_free_occurrence
from ._serialize import parse_graph, serialize_graph

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._enums import DocumentShapeLike
    from riko.types._io import PathLike
    from riko.types._pipedef import Embed, PipeDag, PipeDefLike
    from riko.types._workflow import EdgeFamily, WorkflowDocument


_EMPTY_INPUTS: FrozenDict[str, FrozenJSON] = FrozenDict()
_EMPTY_OUTPUTS: FrozenDict[str, Endpoint] = FrozenDict()
_EMPTY_NODES: FrozenDict[NodeId, Node] = FrozenDict()
_EMPTY_EDGES: tuple[Edge, ...] = ()
_EMPTY_RESOURCES: tuple[str, ...] = ()

type WorkflowLike = Workflow | RawWorkflow | Mapping[str, object]
type NodesInput = Iterable[Node]
type OutputsInput = Mapping[str, Endpoint]

endpoint_freezer = instances_freezer(Endpoint, "Workflow output")
outputs_converter = mapping_converter(
    endpoint_freezer, OutputsInput, what="Workflow 'outputs'"
)
inputs_converter = mapping_converter(freeze_json, what="Workflow 'inputs'")

resource_names_converter = partial(
    normalize_strs, what="Workflow 'resources'", strict=True
)


def _edges_converter(value: Iterable[Edge]) -> tuple[Edge, ...]:
    """Requires every workflow edge to be an ``Edge``."""
    edges = require_sequence(value, "Workflow 'edges'")
    return tuple(require_instances(Edge, edges, "Workflow edge"))


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


@define(frozen=True, slots=True, repr=False)
class Workflow:
    """
    The strict in-memory workflow graph: nodes, edges, outputs, and input declarations.

    Construction canonicalizes field-local representation details such as immutable
    mappings and resource-name shorthand. Does not perform shorthand normalization
    or closed-schema rejection. Cross-field graph validity is checked explicitly by
    ``validate()``. ``parse()`` and ``load()`` read a workflow from any readable
    workflow input, and ``serialize()`` writes it back out as a workflow document.

    Attributes:

        nodes: The graph nodes (given as an iterable and stored keyed by node id).
        module_nodes: The nodes that run a module, keyed by node id.
        callable_nodes: The nodes that run a callable, keyed by node id.
        runnable_nodes: The nodes that run a module or a callable, keyed by node id.
        embeds: The module name and conf each loop node runs per item, keyed by node id.
        index: The graph index derived from the nodes, edges, and outputs.
        edges: The stream and publish edges, in listing order.
        outputs: The workflow outputs: named endpoints the workflow exposes.
        inputs: The declared JSON Schemas.
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
        >>> flow.isvalid
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

    @classmethod
    def parse(
        cls,
        document: WorkflowDocument | str | WorkflowLike | PipeDefLike | PipeDag,
        *,
        shape: DocumentShapeLike | None = None,
    ) -> Self:
        """
        Parses a workflow input of any readable shape into a validated ``Workflow``.

        A workflow document, a serialized pipe definition (``PipeDef``), and a
        serialized ``PipeDag`` are each recognized from their structure, as text,
        bytes, or an already parsed mapping. A mapping listing ``modules`` with neither
        ``src``/``tgt`` wires nor an ``output`` node reads as a ``PipeDag``. A
        ``Workflow`` is re-normalized, so parsing a result again returns an equal
        ``Workflow``.

        Args:

            document: The workflow input.

            shape: The shape to read it as (``"dag"``, ``"v1"``, or ``"v2"``). Omit it
                to detect the shape from the input. A ``Workflow`` reads only as
                ``"v2"``.

        Returns:

            The validated ``Workflow``.

        Raises:

            InvalidPipelineError: If ``document`` is not valid JSON or not a mapping,
                its shape cannot be detected, it does not hold the shape it is read
                as, or the resulting workflow is invalid.

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
            >>> fan_in = {
            ...     "modules": [
            ...         {"id": "a", "name": "fetch"},
            ...         {"id": "b", "name": "fetch"},
            ...         {"id": "u", "name": "union"},
            ...     ],
            ...     "wires": [["a", "u"], ["b", "u", "in:1"]],
            ... }
            >>> [edge.target.port for edge in Workflow.parse(fan_in).edges]
            ['in', 'in:1']
            >>> Workflow.parse("[]")
            Traceback (most recent call last):
            ...
            riko.base.exceptions.InvalidPipelineError: ...workflow must be a mapping

        """
        resolved = resolve_enum(DocumentShape, shape, "shape", strict=False)

        if not isinstance(document, Workflow):
            fields = parse_graph(document, shape=resolved)
        elif resolved is None or resolved is DocumentShape.V2:
            fields = build_workflow_fields(build_raw_graph(document))
        else:
            msg = f"a Workflow can only be read as shape 'v2', not {resolved.value!r}"
            raise InvalidPipelineError(msg)

        flow = cls(**fields)
        flow.validate()
        return flow

    @classmethod
    def load(cls, path: PathLike, *, shape: DocumentShapeLike | None = None) -> Self:
        """
        Loads a validated ``Workflow`` from a JSON file of any readable shape.

        Args:

            path: The file to read.

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

        Args:

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
        return serialize_graph(self, indent=indent)

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

    def family_sources(self, family: EdgeFamily = "stream") -> Counter[tuple[str, str]]:
        edges = get_family_edges(self.edges, family)
        return Counter((edge.source.node, edge.source.port) for edge in edges)

    def family_ports(self, family: EdgeFamily = "stream") -> Counter[tuple[str, str]]:
        edges = get_family_edges(self.edges, family)
        return Counter((edge.target.node, edge.target.port) for edge in edges)

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

    def with_node(self, node: Node) -> Self:
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
                both define the same non-default workflow output; or both declare the
                same input differently.

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
        inputs = other.inputs

        if tail is not None and other.nodes and len(heads) != 1:
            msg = "an appended workflow needs exactly one node with an open input, "
            msg += f"not {len(heads)}: {heads}"
            raise InvalidPipelineError(msg)
        elif named := (set(self.outputs).intersection(outputs)) - {"default"}:
            msg = f"both workflows define workflow output(s): {sorted(named)}"
            raise InvalidPipelineError(msg)
        elif redeclared := [k for k, v in inputs.items() if self.inputs.get(k, v) != v]:
            msg = f"both workflows declare input(s) differently: {sorted(redeclared)}"
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
            inputs={**self.inputs, **inputs},
            edges=[*self.edges, *wiring, *edges],
            resources=unique_everseen(chain(self.resources, other.resources)),
        )

    def validate(self) -> None:
        """
        Validate workflow graph structure and references.

        Raises:

            InvalidPipelineError: If the graph has an unsupported version, an empty node
                set, a dangling edge or output reference, more than one stream edge into
                a port, a publish/subscribe edge mismatch, a misdirected or malformed
                port, a cycle, an unresolved resource, or no workflow output.

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
        family_sources = self.family_sources().items()

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

            >>> from riko.ext import ModuleNode, WriteNode
            >>>
            >>> write = WriteNode(id="w", name="write", backend="file", dest="out.csv")
            >>> flow = Workflow(
            ...     nodes=[ModuleNode(id="a", name="hash"), write],
            ...     outputs={"default": Endpoint("a", "out")},
            ... )
            >>> flow.require_runnable_only("execution")
            Traceback (most recent call last):
                ...
            riko.base.exceptions.InvalidPipelineError: ...execution is not yet supported

        """
        supported = self.runnable_nodes
        nodes = (node for key, node in self.nodes.items() if key not in supported)

        if stray := sorted({node.family for node in nodes}):
            msg = f"{', '.join(stray)} node {what} is not yet supported"
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


def normalize_workflow(value: WorkflowLike) -> Workflow:
    """
    Normalizes a flexible ``WorkflowLike`` into a strict ``Workflow``.

    A ``Workflow`` is re-normalized through the same normalization rather than trusted,
    so a hand-built workflow is re-canonicalized and normalization is idempotent on
    its own output.

    This is the one structural normalization boundary: no compiler, runtime, or CLI
    subsystem independently reinterprets shorthand, legacy port names, or omitted
    outputs. It stays contract-free and does not validate the result; call
    ``validate()`` for that.

    Args:

        value: A ``WorkflowLike`` with ``nodes`` and optional ``edges``, ``outputs``,
            ``inputs``, ``resources``, and ``version``.

    Returns:

        The normalized ``Workflow``.

    Raises:

        InvalidPipelineError: If ``value`` is not a mapping, its structure is
            malformed, or it is a ``Workflow`` with a callable node.

    Examples:

        >>> from riko.ext import normalize_workflow
        >>>
        >>> flow = normalize_workflow(
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
        >>> flow.nodes["write-1"].backend.value
        'file'
        >>> flow.outputs["default"]
        Endpoint(node='write-1', port='out')

    """
    raw = build_raw_graph(value) if isinstance(value, Workflow) else value
    return Workflow(**build_workflow_fields(raw))


def migrate_v1_to_v2(pipe_def: PipeDefLike) -> Workflow:
    """
    Migrates a ``PipeDef`` into a ``Workflow``.

    Warns that a ``PipeDef`` was migrated, then returns the ``Workflow``. Legacy ports,
    the ``write`` module, and the ``PipeDef`` ``output`` node (``_OUTPUT``) are
    translated to their ``Workflow`` equivalents. Orphan nodes are kept, and run only
    when a workflow output needs them. Empty-graph rejection is left to validation.

    A module's call options become the node's ``options``, a loop's embedded module and
    its configuration become the node's ``embed``, and a ``write`` module's file-open
    mode maps to a reconcile mode. A module key with no ``Workflow`` equivalent is
    rejected rather than silently dropped.

    Args:

        pipe_def: A ``PipeDef`` with ``modules`` and ``src``/``tgt`` ``wires``;
            editor ``layout``/``terminaldata`` are ignored.

    Returns:

        The ``Workflow``.

    Raises:

        InvalidPipelineError: If a module or wire is malformed, or a module key has
            no ``Workflow`` equivalent.

    Examples:

        >>> from riko.ext import migrate_v1_to_v2
        >>>
        >>> pipe_def = {
        ...     "modules": [
        ...         {"id": "sw-1", "type": "fetch", "conf": {}},
        ...         {"id": "sw-2", "type": "write", "conf": {"fmt": "json"}},
        ...     ],
        ...     "wires": [
        ...         {
        ...             "id": "_w1",
        ...             "src": {"id": "_OUTPUT", "moduleid": "sw-1"},
        ...             "tgt": {"id": "_INPUT", "moduleid": "sw-2"},
        ...         }
        ...     ],
        ... }
        >>> flow = migrate_v1_to_v2(pipe_def)
        >>> node = flow.nodes["sw-2"]
        >>> node.backend.value, node.fmt.value
        ('file', 'json')
        >>> flow.outputs["default"]
        Endpoint(node='sw-2', port='out')

    """
    return Workflow(**build_workflow_fields(migrate_pipe_def(pipe_def)))


__all__ = ["Workflow", "migrate_v1_to_v2", "normalize_workflow"]
