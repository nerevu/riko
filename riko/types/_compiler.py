"""
Pipe definition and bare-bones DAG typing contracts.

A pipe definition (``PipeDef``) is the older ``src``/``tgt``-wired module listing; a
``PipeDag`` is the bare-bones DAG mapping. Both expand into a ``Workflow``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal, NewType, NotRequired, Required, TypedDict

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
    """
    A pipe definition: the older ``src``/``tgt``-wired module listing.

    ``migrate_v1_to_v2`` converts one into a ``Workflow``.
    """

    modules: list[PipeModule]
    wires: list[Wire]
    layout: NotRequired[list[LayoutItem]]
    terminaldata: NotRequired[list[TerminalDataEntry]]


type PipeDefLike = PipeDef | Mapping[str, object]
type ModuleOptionValues = bool | str | CountValues


class DagModule(TypedDict):
    id: NotRequired[str]
    type: ModuleId | PipeId
    conf: NotRequired[Conf]
    options: NotRequired[ModuleOptions]


class PipeDag(TypedDict):
    """
    A bare-bones DAG mapping that ``parse_dag`` expands into a ``Workflow``.

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
