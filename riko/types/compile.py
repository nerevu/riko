from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

from .modules import EmbedRef

if TYPE_CHECKING:
    from ._module_ids import ModuleId
    from ._pipeline import PyInput
    from .modules import AnyModuleRawConf, Conf, CountValues, LoopableEmbedRef, PipeId


class XY(TypedDict):
    x: int
    y: int


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


class AbbrevStringModule(TypedDict):
    alias: str
    name: str
    pipe_name: str
    is_sub_pipe: bool


class StringModule(AbbrevStringModule):
    id: str
    expr: str
    splits: int
    is_collection: bool


class TemplateData(TypedDict):
    uniq_modules: list[AbbrevStringModule]
    modules: list[StringModule]
    pipe_name: str
    inputs: PyInput
    dependencies: list[str]
    embedded_pipes: dict[str, PipeModule]
    last_module: str
    raw_confs: list[str]
    use_collection: bool
    needs_await: bool
    subtype: str


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


@dataclass(frozen=True, slots=True)
class _Edge:
    """
    One directed connection between two module ports.

    Ports keep their legacy identifiers verbatim (``_INPUT``/``_OTHER``/``_OUTPUT``
    for structural wiring, or a named keyword such as ``count``/``url`` for a named
    secondary input) so the connection's meaning is interpreted in one place rather
    than re-derived from raw wires at every call site.

    Attributes:

        source: Python-safe id of the module the connection leaves.
        target: Python-safe id of the module the connection enters.
        source_port: Raw output-port id on ``source`` (e.g. ``_OUTPUT``).
        target_port: Raw input-port id on ``target`` (e.g. ``_INPUT``/``count``).

    """

    source: str
    target: str
    source_port: str
    target_port: str


@dataclass(frozen=True, slots=True)
class _OutputRef:
    """
    A canonical pipeline output to replace the legacy ``_OUTPUT`` node.

    Attributes:

        node: Python-safe id of the module that produces the output stream.
        port: Canonical output-port name.

    """

    node: str
    port: str


@dataclass(frozen=True, slots=True)
class _GraphIndex:
    """
    Immutable, runtime-neutral interpretation of a pipe's wiring.

    Built once per parse so both the current compiler and future execution planning
    consume the same structural facts instead of rescanning raw wires. Edge lookups
    (``incoming``/``outgoing``) carry full port identity. The
    ``dependencies``/``dependents`` projection carries only node-level ordering.

    Attributes:

        edges: Every wire connection, in listing order.
        incoming: Connections entering each node, keyed by target id.
        outgoing: Connections leaving each node, keyed by source id.
        dependencies: Node ids each node must run after.
        dependents: Node ids that must run after each node.
        order: Node ids in topological (execution) order.
        roots: Node ids with no dependencies, in ``order``.
        leaves: Node ids with no dependents, in ``order``.
        outputs: Canonical pipeline outputs, keyed by output name.

    """

    edges: tuple[_Edge, ...]
    incoming: Mapping[str, tuple[_Edge, ...]]
    outgoing: Mapping[str, tuple[_Edge, ...]]
    dependencies: Mapping[str, frozenset[str]]
    dependents: Mapping[str, frozenset[str]]
    order: tuple[str, ...]
    roots: tuple[str, ...]
    leaves: tuple[str, ...]
    outputs: Mapping[str, _OutputRef]


class ParsedPipeDef(TypedDict):
    name: str
    modules: dict[str, PipeModule]
    embed: dict[str, PipeModule]
    graph: _GraphIndex


class PipelineDescription(TypedDict):
    inputs: list[str | tuple[str, ...]]
    dependencies: list[str]


class DagModule(TypedDict):
    id: NotRequired[str]
    type: ModuleId | PipeId
    conf: AnyModuleRawConf


class PipeDag(TypedDict):
    """
    Bare-bones DAG expanded by ``riko.compile.convert_dag``.

    ``wires`` is optional (omit for a linear chain in module listing order) and
    holds ``(source_id, target_id)`` pairs. A module ``id`` is also optional and
    defaults to ``sw-{n}`` (1-based listing order) — practical for the concise
    wireless form; supply ids when ``wires`` reference them. Every expanded wire
    targets ``_INPUT``, so fan-in operators such as ``union``/``join`` (whose
    secondary inputs need ``_OTHER{n}`` targets) cannot be expressed here and
    must be authored as a full ``PipeDef``.
    """

    modules: list[DagModule]
    wires: NotRequired[list[tuple[str, str]]]


type PipelineDescriptionLike = PipelineDescription | str | tuple[str, ...]
type PipelineDescriptions = Sequence[PipelineDescriptionLike]
type PipelineDescriptionStream = Iterator[PipelineDescriptionLike]

__all__ = [
    "DagModule",
    "LoopModule",
    "ParsedPipeDef",
    "PipeDag",
    "PipeDef",
    "PipeModule",
    "PipelineDescription",
    "Wire",
]
