"""Pipe-definition, bare DAG, and workflow graph-index typing contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING, Literal, NewType, NotRequired, Required, TypedDict

from ._workflow import parse_port

if TYPE_CHECKING:
    from ._module_ids import LoopableModuleId, ModuleId
    from .modules import AnyModuleRawConf, Conf, ModuleOptions


PipeId = NewType("PipeId", str)
CountValues = Literal["first", "all"]


class EmbedRef(TypedDict):
    id: str
    type: ModuleId | PipeId | Literal["output"]


class LoopableEmbedRef(TypedDict):
    id: str
    type: LoopableModuleId | PipeId


class LayoutItem(TypedDict):
    id: str
    xy: tuple[int, int]


class PipeModule(EmbedRef, total=False):
    conf: Required[AnyModuleRawConf]
    emit: bool
    assign: str
    field: str
    count: CountValues


class LoopModule(PipeModule, total=False):
    embed: Required[LoopableEmbedRef]


class EmbedKwargs(TypedDict, total=False):
    """Kwargs a loop passes to its embed per parent — not a full module descriptor."""

    conf: Conf
    field: str
    emit: bool


class TypeCount(TypedDict):
    _count: str
    _type: str


class AttrGroup(TypedDict, total=False):
    content: TypeCount
    isPermaLink: TypeCount
    height: TypeCount
    type: TypeCount
    url: TypeCount
    width: TypeCount
    role: TypeCount
    day: TypeCount
    day_of_week: TypeCount
    hour: TypeCount
    minute: TypeCount
    month: TypeCount
    second: TypeCount
    timezone: TypeCount
    utime: TypeCount
    year: TypeCount
    permalink: TypeCount
    value: TypeCount


class FieldWithAttr(TypedDict):
    _type: str
    _attr: NotRequired[AttrGroup]
    _count: NotRequired[str]


ItemAttr = TypedDict(
    "ItemAttr",
    {
        "category": TypeCount,
        "description": TypeCount | FieldWithAttr,
        "guid": FieldWithAttr,
        "link": TypeCount,
        "lostattribute": TypeCount,
        "media:content": FieldWithAttr,
        "media:credits": FieldWithAttr,
        "media:text": FieldWithAttr,
        "media:thumbnail": FieldWithAttr,
        "newtitle": TypeCount,
        "pubDate": TypeCount,
        "source": TypeCount,
        "title": TypeCount,
        "y:id": FieldWithAttr,
        "y:published": FieldWithAttr,
        "y:title": TypeCount,
    },
)


class TerminalData(TypedDict):
    _type: str
    _attr: NotRequired[ItemAttr]
    _count: NotRequired[str]


class TerminalDataEntry(TypedDict):
    id: str
    moduleid: str
    data: TerminalData


class WireEndpoint(TypedDict):
    id: str
    moduleid: str


class Wire(TypedDict):
    id: str
    src: WireEndpoint
    tgt: WireEndpoint


class PipeDef(TypedDict):
    modules: list[PipeModule]
    wires: list[Wire]
    layout: NotRequired[list[LayoutItem]]
    terminaldata: NotRequired[list[TerminalDataEntry]]


type PipeDefLike = PipeDef | Mapping[str, object]
type ModuleOptionValues = bool | str | CountValues


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


@dataclass(frozen=True, slots=True)
class OutputRef:
    """
    One named output of a workflow.

    Attributes:

        node: Id of the node that produces the output stream.
        port: Output port on ``node`` (e.g. ``out``).

    """

    node: str
    port: str


@dataclass(frozen=True, slots=True)
class GraphIndex:
    """
    Immutable, runtime-neutral interpretation of a workflow's topology.

    Execution planning and both sync and async executions read the same
    structural facts from one index rather than rescanning the workflow's edges.
    Edge lookups (``incoming``/``outgoing``) carry full port identity. The
    ``dependencies``/``dependents`` projection carries only node-level ordering.

    Attributes:

        edges: Every stream edge, in listing order.
        incoming: Connections entering each node, keyed by target id.
        outgoing: Connections leaving each node, keyed by source id.
        dependencies: Node ids each node must run after.
        dependents: Node ids that must run after each node.
        order: Node ids in topological (execution) order.
        roots: Node ids with no dependencies, in ``order``.
        leaves: Node ids with no dependents, in ``order``.
        outputs: The workflow's named outputs, keyed by output name.

    """

    edges: tuple[GraphEdge, ...]
    incoming: Mapping[str, tuple[GraphEdge, ...]]
    outgoing: Mapping[str, tuple[GraphEdge, ...]]
    dependencies: Mapping[str, frozenset[str]]
    dependents: Mapping[str, frozenset[str]]
    order: tuple[str, ...]
    roots: tuple[str, ...]
    leaves: tuple[str, ...]
    outputs: Mapping[str, OutputRef]

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
            attr_: Mapping[str, tuple[GraphEdge, ...]] = getattr(self, attr)
            edges = attr_.get(root, ()) if root else chain.from_iterable(attr_.values())
            valid = all(edge.is_valid for edge in edges)
        else:
            msg = f"invalid {attr=}; must be 'incoming', 'outgoing', or 'edges'"
            raise ValueError(msg)

        return valid


class DagModule(TypedDict):
    id: NotRequired[str]
    type: ModuleId | PipeId
    conf: NotRequired[Conf]
    options: NotRequired[ModuleOptions]


class PipeDag(TypedDict):
    """
    Bare-bones DAG expanded by ``riko.runtime._migrate.parse_dag``.

    ``wires`` is optional (omit for a linear chain in module listing order) and
    holds ``(source_id, target_id)`` entries, optionally followed by the port the
    wire enters — so a fan-in operator such as ``union``/``join`` is expressible
    as ``("b", "union-1", "in:1")``. A module ``id`` is also optional and defaults
    to ``sw-{n}`` (1-based listing order) — practical for the concise wireless
    form; supply ids when ``wires`` reference them. The expansion adds no terminal
    output node: the workflow's default output is its single leaf.
    """

    modules: list[DagModule]
    wires: NotRequired[Sequence[Sequence[str]]]


__all__ = [
    "DagModule",
    "LoopModule",
    "PipeDag",
    "PipeDef",
    "PipeDefLike",
    "PipeModule",
    "Wire",
]
