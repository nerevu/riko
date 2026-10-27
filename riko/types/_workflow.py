# vim: sw=4:ts=4:expandtab
"""
Structural contracts for the ``Workflow`` graph language.

These are pure, behavior-free contracts shared by the immutable workflow model in
``riko.definitions``: the node/port endpoint reference, the port-grammar parser, the
input reference shape, and the node/edge discriminant vocabularies. The concrete node,
edge, and ``Pipeline`` definitions build on these.

Examples:

    Basic usage::

        >>> from riko import Endpoint
        >>> from riko.types._workflow import parse_port
        >>>
        >>> Endpoint("normalize-1", "out")
        Endpoint(node='normalize-1', port='out')
        >>> parse_port("out:errors")
        ParsedPort(direction='out', index=None, name='errors')

"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property, partial
from itertools import chain
from operator import attrgetter
from types import ModuleType
from typing import TYPE_CHECKING, ClassVar, Literal, NewType, Required, TypedDict, cast

from attrs import define, field

from riko.base._graph import (
    cyclic_nodes,
    descendants,
    edges_to_graph,
    leaves,
    reverse_graph,
    topological_sort,
)
from riko.base._iterutils import map_values
from riko.base._require_guards import (
    require_instance,
    require_nonblank_str,
    require_str,
    validator_from_require,
)

from ._frozendict import FrozenDict, freeze

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ._enums import BackendLike, FmtLike, StrLike
    from ._frozendict import FrozenSetMapping, FrozenTupleMapping
    from ._io import PathLike
    from ._options import RawCallOptions
    from ._pipedef import Embed
    from .modules import Conf

type NodeId = str
type Port = str
type ResourceName = str
type WorkflowDocument = bytes
type DocumentNodeFamily = Literal[
    "module", "read", "write", "cache", "action", "subscribe"
]
type NodeFamily = DocumentNodeFamily | Literal["callable"]
type EdgeFamily = Literal["stream", "publish"]
type PortDirection = Literal["in", "out"]

WORKFLOW_VERSION = "2"
WorkflowModule = NewType("WorkflowModule", str)
ResolvedWorkflow = NewType("ResolvedWorkflow", ModuleType)


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


class RawNode(TypedDict, total=False):
    """Shorthand for a node of any family."""

    id: str
    name: Required[str]
    family: DocumentNodeFamily
    label: str
    conf: Conf | Mapping[str, object]
    options: RawCallOptions | Mapping[str, object]
    embed: Embed | Mapping[str, object]
    policy: Mapping[str, object]
    params: Mapping[str, object]
    backend: BackendLike
    dest: PathLike
    fmt: FmtLike
    format: FmtLike
    mode: str
    keys: StrLike
    resources: str | Sequence[str] | Mapping[str, str]


class RawWorkflow(TypedDict, total=False):
    """Shorthand workflow mapping that is normalized into a ``Workflow``."""

    nodes: Sequence[RawNode] | Mapping[str, RawNode]
    outputs: Mapping[str, RawEndpoint]
    inputs: Mapping[str, str | Mapping[str, object]]
    edges: Sequence[RawEdge]
    resources: str | Sequence[str]
    version: str


@define(frozen=True, slots=True)
class Endpoint:
    """
    A reference to one port on one node that edges and outputs point through.

    Attributes:

        node: The id of the node, named like the serialized endpoint's ``node`` key.
        port: The port on that node (e.g. ``out``/``in``/``in:1``).

    """

    node: NodeId = field(validator=validator_from_require(require_nonblank_str))
    port: Port = field(validator=validator_from_require(require_str))

    def __str__(self) -> str:
        return f"Endpoint({self.node!r}, {self.port!r})"


_is_endpoint = validator_from_require(require_instance, Endpoint)


@define(frozen=True, slots=True)
class Edge:
    """A directed edge from a source port to a target port; its family says how."""

    family: ClassVar[EdgeFamily]
    source: Endpoint = field(validator=_is_endpoint)
    target: Endpoint = field(validator=_is_endpoint)

    def __str__(self) -> str:
        return f"{type(self).__name__}({self.source}, {self.target})"


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
    One directed edge between two workflow node ports.

    Ports keep their workflow spelling: ``out`` on the source, and on the target either
    the default ``in``, a positional ``in:1``/``in:2`` input port, or a named input port
    such as ``in:count``. Every input port delivers a stream. ``is_default`` reports
    whether the target port is the default one.

    Attributes:

        source: Id of the node the edge leaves.
        target: Id of the node the edge enters.
        source_port: Output port on ``source`` (e.g. ``out``).
        target_port: Input port on ``target`` (e.g. ``in``/``in:1``/``in:count``).

    """

    source: str
    target: str
    source_port: str
    target_port: str

    @property
    def is_default(self) -> bool:
        return parse_port(self.target_port).is_default


@define(frozen=True, slots=True)
class GraphIndex:
    """
    Immutable, runtime-neutral interpretation of a workflow's topology.

    Workflow validation, execution planning, and both sync and async executions read the
    same structural facts from one index rather than rescanning the workflow's edges.
    Callers only supply the nodes, edges, and outputs. ``Workflow.validate()`` is where
    structural errors surface. A hand-built index whose output names a missing node
    raises ``KeyError`` from ``required`` only when that attribute is read.

    Edge lookups (``incoming``/``outgoing``) carry full port identity. The ``upstream``/
    ``downstream`` projection carries only node-level ordering.

    Attributes:

        node_ids: Every node id, in declaration order.
        edges: Every edge, in listing order.
        outputs: The workflow outputs, keyed by name.
        incoming: Edges entering each node, keyed by target id.
        outgoing: Edges leaving each node, keyed by source id.
        downstream: Node ids that must run after each node.
        upstream: Node ids each node must run after.
        order: Node ids in topological (execution) order.
        cyclic: Node ids that lie on a cycle, sorted.
        roots: Node ids with no upstream nodes, in ``order``.
        leaves: Node ids with no downstream nodes, in declaration order.
        required: Node ids each workflow output subgraph runs (the output's node and
            every node upstream of it), in ``order``.

    Examples:

        >>> edge = GraphEdge("a", "b", "out", "in")
        >>> index = GraphIndex(["a", "b"], [edge], {"default": Endpoint("b", "out")})
        >>> index.order, index.roots, index.leaves
        (('a', 'b'), ('a',), ('b',))
        >>> index.required["default"]
        ('a', 'b')

    """

    node_ids: tuple[NodeId, ...] = field(converter=tuple)
    edges: tuple[GraphEdge, ...] = field(converter=tuple)
    outputs: FrozenDict[str, Endpoint] = field(converter=FrozenDict)

    def _group_edges(self, key: Callable[[GraphEdge], str]) -> FrozenTupleMapping:
        grouped: dict[str, list[GraphEdge]] = defaultdict(list)

        for edge in self.edges:
            grouped[key(edge)].append(edge)

        return FrozenDict.from_frozen(map_values(tuple, grouped))

    @cached_property
    def incoming(self) -> FrozenTupleMapping:
        return self._group_edges(attrgetter("target"))

    @cached_property
    def outgoing(self) -> FrozenTupleMapping:
        return self._group_edges(attrgetter("source"))

    @cached_property
    def downstream(self) -> FrozenSetMapping:
        pairs = ((edge.source, edge.target) for edge in self.edges)
        return freeze(edges_to_graph(pairs, *self.node_ids))

    @cached_property
    def upstream(self) -> FrozenSetMapping:
        return freeze(reverse_graph(self.downstream))

    @cached_property
    def _groups(self) -> tuple[tuple[str, ...], ...]:
        return tuple(topological_sort(self.downstream))

    @cached_property
    def order(self) -> tuple[str, ...]:
        return tuple(chain.from_iterable(self._groups))

    @cached_property
    def cyclic(self) -> tuple[str, ...]:
        return tuple(sorted(cyclic_nodes(self.downstream, list(self._groups))))

    @cached_property
    def roots(self) -> tuple[str, ...]:
        return tuple(node_id for node_id in self.order if not self.upstream[node_id])

    @cached_property
    def leaves(self) -> tuple[str, ...]:
        return tuple(leaves(self.downstream))

    @cached_property
    def required(self) -> FrozenDict[str, tuple[str, ...]]:
        reach = partial(descendants, graph=self.upstream)
        items = self.outputs.items()
        members = {name: reach(ref.node) | {ref.node} for name, ref in items}
        get_ids = lambda value: tuple(_id for _id in self.order if _id in value)
        ordered = map_values(get_ids, members)
        return FrozenDict(ordered)

    def is_open(self, node_id: str) -> bool:
        """
        Reports whether node's default input port can accept a seed.

        Only an edge into the bare default ``in`` port closes it. Positional ``in:<n>``
        and named ``in:<name>`` edges leave it open.

        Args:

            node_id: The id of the node to check.

        Returns:

            ``True`` when no edge targets the node's default input port.

        Examples:

            >>> named = GraphEdge("a", "c", "out", "in:count")
            >>> default = GraphEdge("b", "d", "out", "in")
            >>> index = GraphIndex(["a", "b", "c", "d"], [named, default], {})
            >>> index.is_open("c"), index.is_open("d")
            (True, False)

        """
        return not any(map(attrgetter("is_default"), self.incoming.get(node_id, ())))


__all__ = [
    "WORKFLOW_VERSION",
    "DocumentNodeFamily",
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
