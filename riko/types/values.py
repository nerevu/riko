from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, auto
from time import struct_time
from typing import TYPE_CHECKING, NotRequired, TypeAlias, TypedDict, Union
from xml.sax import SAXParseException  # noqa: S406

if TYPE_CHECKING:
    from riko import Objconf, Objectify
    from riko.dotdict import DotDict
    from riko.types.compile import PipeModule, Wire
    from riko.types.general import Defaults
    from riko.types.modules import AnyModuleConf, ParsedParam, RegexRule


# Misc
class StreamState(Enum):
    PENDING = auto()
    DONE = auto()


class AuthorDetail(TypedDict, total=False):
    href: str
    name: str
    email: str


class FeedParserRSSEntry(TypedDict):
    author: str | None
    author_detail: AuthorDetail
    id: str | None
    pubDate: NotRequired[struct_time | None]
    published_parsed: NotRequired[struct_time | None]
    title: str | None
    updated_parsed: NotRequired[struct_time | None]


YahooRSSEntry = TypedDict(
    "YahooRSSEntry",
    {
        "author.name": str | None,
        "author.uri": str | None,
        "dc:creator": str | None,
        "y:id": str | None,
        "y:published": str | struct_time | None,
        "y:title": str | None,
    },
)


RSSEntry = TypedDict(
    "RSSEntry",
    {
        "author": str | None,
        "author.name": str | None,
        "author.uri": str | None,
        "author_detail": AuthorDetail,
        "dc:creator": str | None,
        "id": str | None,
        "pubDate": struct_time | None,
        "published_parsed": NotRequired[struct_time | None],
        "title": str | None,
        "updated_parsed": struct_time | None,
        "y:id": str | None,
        "y:published": str | struct_time | None,
        "y:title": str | None,
    },
)


class RSSParseResult(TypedDict):
    entries: list[FeedParserRSSEntry]
    bozo: NotRequired[bool]
    bozo_exception: NotRequired[SAXParseException | Exception]


class StatefulItem(TypedDict):
    state: StreamState


# Instance Types
StrictDateType = date | datetime | struct_time
DateLikeType = (str, int, date, datetime, struct_time)
NumLikeType = (float, int, Decimal)
IntermediateValueType = (
    str,
    int,
    float,
    Decimal,
    date,
    datetime,
    struct_time,
    bool,
    type(None),
)

# Basic
BasicValue: TypeAlias = str | int
BasicMapping: TypeAlias = Mapping[str, "BasicArg"]
BasicSequence: TypeAlias = Sequence["BasicArg"]
BasicArg: TypeAlias = BasicValue | BasicMapping | BasicSequence
BasicDict: TypeAlias = dict[str, "BasicAnyReturn"]
BasicList: TypeAlias = list["BasicAnyReturn"]
BasicAnyReturn: TypeAlias = BasicDict | BasicList | BasicValue

# Intermediate
StrictDate: TypeAlias = date | datetime | struct_time
DateLike: TypeAlias = BasicValue | StrictDate
NumLike: TypeAlias = float | int | Decimal
SortableValue: TypeAlias = BasicValue | DateLike | NumLike | bool

IntermediateValue: TypeAlias = SortableValue | None
IntermediateMapping: TypeAlias = Union[
    BasicMapping, Mapping[str, "IntermediateArg"], "DotDict"
]
IntermediateSequence: TypeAlias = Sequence["IntermediateArg"]
IntermediateArg: TypeAlias = (
    IntermediateValue | IntermediateMapping | IntermediateSequence
)

# Complex
DateDict: TypeAlias = dict[str, str | int | date | bool]
ComplexDict: TypeAlias = dict[str, "ComplexArg"]
Location: TypeAlias = Mapping[str, str | float]
IPAddress: TypeAlias = Mapping[str, str]
CurrencyCode: TypeAlias = Mapping[str, str | int | float]
AnyLocation: TypeAlias = Location | IPAddress | CurrencyCode

ComplexMapping: TypeAlias = Union[
    "AnyModuleConf",
    "Objconf",
    "Objectify",
    "RegexRule",
    "Wire",
    DateDict,
    IntermediateMapping,
    Location,
    Mapping[str, "ComplexArg"],
    RSSEntry,
    StatefulItem,
    "ParsedParam",
    "PipeModule",
    "Defaults",
]
ComplexValue: TypeAlias = IntermediateValue | AnyLocation
ComplexSequence: TypeAlias = Sequence["ComplexArg"]
ComplexArg: TypeAlias = ComplexValue | ComplexMapping | ComplexSequence
