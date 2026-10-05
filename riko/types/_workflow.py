# vim: sw=4:ts=4:expandtab
"""
Structural contracts for the ``Workflow`` graph language.

These are pure, behavior-free contracts shared by the immutable workflow model in
``riko.definitions``: the node/port endpoint reference, the port-grammar parser, the
input reference shape, and the node/edge discriminant vocabularies. The concrete node,
edge, and ``Pipeline`` definitions build on these.

Examples:

    Basic usage::

        >>> from riko.types._workflow import Endpoint, parse_port
        >>>
        >>> Endpoint("normalize-1", "out")
        Endpoint(node='normalize-1', port='out')
        >>> parse_port("out:errors")
        ParsedPort(direction='out', index=None, name='errors')

"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING, ClassVar, Literal, Required, TypedDict, cast

from attrs import Factory, define, field

from riko.base._graph import (
    cyclic_nodes,
    descendants,
    edges_to_graph,
    leaves,
    reverse_graph,
    topological_groups,
)

from ._collections import FreezeMapping, FreezeSetMapping, FreezeTupleMapping

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ._collections import (
        FrozenMap,
        FrozenSetMapping,
        FrozenTupleMapping,
        JSONSchema,
    )
    from ._enums import BackendLike, FmtLike, StrLike
    from .modules import Conf

type NodeId = str
type Port = str
type ResourceName = str
type WorkflowDocument = bytes
type WorkflowModule = str

type NodeFamily = Literal["module", "read", "write", "cache", "action", "subscribe"]
type EdgeFamily = Literal["stream", "publish"]
type PortDirection = Literal["in", "out"]

WORKFLOW_VERSION = "2"


class InputRef(TypedDict):
    """A structural reference to a declared workflow input."""

    input: str


class RawEndpoint(TypedDict, total=False):
    """Shorthand for an edge or output endpoint; ``node`` is required."""

    node: Required[str]
    port: str


class RawEdge(TypedDict, total=False):
    """Shorthand for a stream or publish edge between two endpoints."""

    source: Required[RawEndpoint]
    target: Required[RawEndpoint]
    family: EdgeFamily
    type: EdgeFamily


class RawNode(TypedDict, total=False):
    """Shorthand for a node of any family, with aliases and optional keys."""

    id: str
    name: Required[str]
    type: NodeFamily
    family: NodeFamily
    label: str
    conf: Conf | Mapping[str, object]
    options: Mapping[str, object]
    embed: Mapping[str, object]
    policy: Mapping[str, object]
    params: Mapping[str, object]
    backend: BackendLike
    dest: str
    fmt: FmtLike
    format: FmtLike
    mode: str
    keys: StrLike
    resources: str | Sequence[str] | Mapping[str, str]


class RawWorkflow(TypedDict, total=False):
    """Shorthand workflow mapping a person writes, normalized into a ``Workflow``."""

    nodes: Sequence[RawNode] | Mapping[str, RawNode]
    outputs: Mapping[str, RawEndpoint]
    inputs: JSONSchema
    edges: Sequence[RawEdge]
    resources: str | Sequence[str]
    version: str


@define(frozen=True, slots=True)
class Endpoint:
    """A reference to one port on one node; edges and outputs point through it."""

    node: NodeId
    port: Port

    def __str__(self) -> str:
        return f"Endpoint({self.node!r}, {self.port!r})"


@define(frozen=True, slots=True)
class Edge:
    """A stream edge delivering records from a source port to a target port."""

    family: ClassVar[EdgeFamily]
    source: Endpoint
    target: Endpoint

    def __str__(self) -> str:
        return f"{type(self).__name__}({self.source}, {self.target})"

    @property
    def port(self) -> tuple[str, str]:
        return self.target.node, self.target.port


@dataclass(frozen=True, slots=True)
class ParsedPort:
    """The parsed structure of a port: direction with an optional position or name."""

    direction: PortDirection
    index: int | None
    name: str | None

    @property
    def is_default(self) -> bool:
        return self.index is None and self.name is None

    @property
    def is_positional(self) -> bool:
        return self.index is not None


def parse_port(port: Port) -> ParsedPort:
    """
    Parses a port string into its direction and optional position or name.

    Args:

        port: A port following the ``in``/``out``, ``in:N``/``out:N`` (``N`` is
            1-based), or ``in:<name>``/``out:<name>`` grammar.

    Returns:

        The parsed direction, positional index, and semantic name.

    Examples:

        >>> parse_port("in")
        ParsedPort(direction='in', index=None, name=None)
        >>> parse_port("out:1")
        ParsedPort(direction='out', index=1, name=None)
        >>> parse_port("in:count")
        ParsedPort(direction='in', index=None, name='count')
        >>> parse_port("in:0")
        Traceback (most recent call last):
        ValueError: invalid port: 'in:0'

    """
    direction, sep, rest = port.partition(":")

    if direction not in {"in", "out"}:
        raise ValueError(f"invalid port direction: {port!r}")

    if not sep:
        index, name = None, None
    elif rest.isdigit() and int(rest) > 0:
        index, name = int(rest), None
    elif rest.isidentifier():
        index, name = None, rest
    else:
        raise ValueError(f"invalid port: {port!r}")

    return ParsedPort(cast("PortDirection", direction), index, name)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """
    One directed stream connection between two workflow node ports.

    Ports keep their workflow spelling: ``out`` on the source, and on the target
    either the default ``in``, a positional ``in:1``/``in:2`` input, or a named
    value input such as ``count``. ``is_valid`` reports whether the target port
    is a positional stream input rather than a named value input.

    Attributes:

        source: Id of the node the connection leaves.
        target: Id of the node the connection enters.
        source_port: Output port on ``source`` (e.g. ``out``).
        target_port: Input port on ``target`` (e.g. ``in``/``in:1``/``count``).

    """

    source: str
    target: str
    source_port: str
    target_port: str

    @property
    def is_valid(self) -> bool:
        return parse_port(self.target_port).is_positional


_freeze_edges = FreezeTupleMapping[str, GraphEdge]()
_freeze_sets = FreezeSetMapping[str, str]()


def _incoming(self: GraphIndex) -> FrozenTupleMapping:
    grouped: dict[str, list[GraphEdge]] = defaultdict(list)

    for edge in self.edges:
        grouped[edge.target].append(edge)

    return _freeze_edges(grouped)


def _outgoing(self: GraphIndex) -> FrozenTupleMapping:
    grouped: dict[str, list[GraphEdge]] = defaultdict(list)

    for edge in self.edges:
        grouped[edge.source].append(edge)

    return _freeze_edges(grouped)


def _dependents(self: GraphIndex) -> FrozenSetMapping:
    pairs = ((edge.source, edge.target) for edge in self.edges)
    return _freeze_sets(edges_to_graph(pairs, *self.nodes))


def _dependencies(self: GraphIndex) -> FrozenSetMapping:
    return _freeze_sets(reverse_graph(self.dependents))


def _components(self: GraphIndex) -> tuple[tuple[str, ...], ...]:
    return tuple(topological_groups(self.dependents))


def _order(self: GraphIndex) -> tuple[str, ...]:
    return tuple(chain.from_iterable(self._groups))


def _cyclic(self: GraphIndex) -> tuple[str, ...]:
    return tuple(sorted(cyclic_nodes(self.dependents, list(self._groups))))


def _roots(self: GraphIndex) -> tuple[str, ...]:
    return tuple(node for node in self.order if not self.dependencies[node])


def _leaves(self: GraphIndex) -> tuple[str, ...]:
    return tuple(leaves(self.dependents))


def _required(self: GraphIndex) -> FrozenSetMapping:
    upstream = partial(descendants, graph=self.dependencies)
    items = self.outputs.items()
    return _freeze_sets({name: upstream(ref.node) | {ref.node} for name, ref in items})


@define(frozen=True, slots=True)
class GraphIndex:
    """
    Immutable, runtime-neutral interpretation of a workflow's topology.

    Workflow validation, execution planning, and both sync and async executions
    read the same structural facts from one index rather than rescanning the
    workflow's edges. Only the nodes, edges, and outputs are supplied; every other
    attribute derives from them, so an index is consistent however it is built.

    Edge lookups (``incoming``/``outgoing``) carry full port identity. The
    ``dependencies``/``dependents`` projection carries only node-level ordering.

    Attributes:

        nodes: Every node id, in declaration order.
        edges: Every edge, in listing order.
        outputs: The workflow's named outputs, keyed by output name.
        incoming: Connections entering each node, keyed by target id.
        outgoing: Connections leaving each node, keyed by source id.
        dependents: Node ids that must run after each node.
        dependencies: Node ids each node must run after.
        order: Node ids in topological (execution) order.
        cyclic: Node ids that lie on a cycle, sorted.
        roots: Node ids with no dependencies, in ``order``.
        leaves: Node ids with no dependents, in declaration order.
        required: For each named output, the node ids its subgraph runs: the
            output's node and every node upstream of it.

    Examples:

        >>> edge = GraphEdge("a", "b", "out", "in")
        >>> index = GraphIndex(["a", "b"], [edge], {"default": Endpoint("b", "out")})
        >>> index.order, index.roots, index.leaves
        (('a', 'b'), ('a',), ('b',))
        >>> sorted(index.required["default"])
        ['a', 'b']

    """

    nodes: tuple[str, ...] = field(converter=tuple)
    edges: tuple[GraphEdge, ...] = field(converter=tuple)
    outputs: FrozenMap[Endpoint] = field(converter=FreezeMapping[str, Endpoint]())
    incoming: FrozenTupleMapping = field(
        init=False, default=Factory(_incoming, takes_self=True)
    )
    outgoing: FrozenTupleMapping = field(
        init=False, default=Factory(_outgoing, takes_self=True)
    )
    dependents: FrozenSetMapping = field(
        init=False, default=Factory(_dependents, takes_self=True)
    )
    dependencies: FrozenSetMapping = field(
        init=False, default=Factory(_dependencies, takes_self=True)
    )
    _groups: tuple[tuple[str, ...], ...] = field(
        init=False, default=Factory(_components, takes_self=True), repr=False, eq=False
    )
    order: tuple[str, ...] = field(init=False, default=Factory(_order, takes_self=True))
    cyclic: tuple[str, ...] = field(
        init=False, default=Factory(_cyclic, takes_self=True)
    )
    roots: tuple[str, ...] = field(init=False, default=Factory(_roots, takes_self=True))
    leaves: tuple[str, ...] = field(
        init=False, default=Factory(_leaves, takes_self=True)
    )
    required: FrozenSetMapping = field(
        init=False, default=Factory(_required, takes_self=True)
    )

    def is_open(
        self,
        root: str | None = None,
        attr: Literal["incoming", "outgoing", "edges"] = "incoming",
    ) -> bool:
        if attr == "edges" and root:
            msg = "cannot validate edges by root; use 'incoming' or 'outgoing'"
            raise ValueError(msg)
        elif attr == "edges":
            valid = all(edge.is_valid for edge in self.edges)
        elif attr in {"incoming", "outgoing"}:
            attr_: FrozenTupleMapping = getattr(self, attr)
            edges = attr_.get(root, ()) if root else chain.from_iterable(attr_.values())
            valid = all(edge.is_valid for edge in edges)
        else:
            msg = f"invalid {attr=}; must be 'incoming', 'outgoing', or 'edges'"
            raise ValueError(msg)

        return valid


__all__ = [
    "WORKFLOW_VERSION",
    "EdgeFamily",
    "Endpoint",
    "GraphEdge",
    "GraphIndex",
    "InputRef",
    "NodeFamily",
    "NodeId",
    "ParsedPort",
    "Port",
    "PortDirection",
    "ResourceName",
    "parse_port",
]
