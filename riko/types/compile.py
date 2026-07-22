from typing import NotRequired, TypedDict

from riko.types.modules import AnyModuleRawConf, ModuleName


class XY(TypedDict):
    x: int
    y: int


class LayoutItem(TypedDict):
    id: str
    xy: tuple[int, int]


class PipeModule(TypedDict):
    id: str
    type: ModuleName
    conf: AnyModuleRawConf


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


class ParsedPipeDef(TypedDict):
    name: str
    modules: dict[str, PipeModule]
    embed: dict[str, PipeModule]
    graph: dict[str, str | list[str]]
    wires: dict[str, Wire]


class DagModule(TypedDict):
    id: NotRequired[str]
    type: ModuleName
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
