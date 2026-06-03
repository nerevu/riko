from typing import TypedDict, NotRequired

from riko.types.modules import AnyModuleConf, ModuleName

XY = TypedDict("XY", {"x": int, "y": int})


class LayoutItem(TypedDict):
    id: str
    xy: tuple[int, int]


class Module(TypedDict):
    id: str
    type: ModuleName
    conf: AnyModuleConf


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


class ItemAttr(TypedDict, total=False):
    category: TypeCount
    description: TypeCount | FieldWithAttr
    guid: FieldWithAttr
    link: TypeCount
    pubDate: TypeCount
    source: TypeCount
    title: TypeCount
    y_title: TypeCount        # was y:title
    y_id: FieldWithAttr       # was y:id
    y_published: FieldWithAttr  # was y:published
    media_content: FieldWithAttr   # was media:content
    media_credits: FieldWithAttr    # was media:credit
    media_text: FieldWithAttr      # was media:text
    media_thumbnail: FieldWithAttr  # was media:thumbnail
    loop_itembuilder: FieldWithAttr  # was loop:itembuilder
    newtitle: TypeCount
    lostattribute: TypeCount


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


endpoint: WireEndpoint = {"id": "id", "moduleid": "id"}
x: Wire = {"id": "1", "src": endpoint, "tgt": endpoint}
y = dict(x)
#
#
# def sanitize_keys(obj: Any) -> Any:
#     """Recursively replace ':' with '_' in all dict keys."""
#     if isinstance(obj, dict):
#         return {k.replace(":", "_"): sanitize_keys(v) for k, v in obj.items()}
#     elif isinstance(obj, list):
#         return [sanitize_keys(item) for item in obj]
#
#     return obj
#
#
# def load_pipeline(raw: dict) -> Pipeline:
#     return cast(Pipeline, sanitize_keys(raw))
