import ast
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, auto
from time import struct_time
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from fastfeedparser import FastFeedParserDict
    from feedparser import FeedParserDict

    from riko.dotdict import DotDict


# Misc
class StreamState(Enum):
    PENDING = auto()
    DONE = auto()


class EntryContent(TypedDict):
    type: str
    value: str
    language: str
    base: str


class Enclosure(TypedDict):
    type: str
    length: int
    href: str


class AuthorDetail(TypedDict):
    href: str
    name: str
    email: str


class CommonRSSEntry(TypedDict):
    author: str | None
    title: str | None
    description: str | None
    link: str
    content: list[EntryContent]
    enclosures: list[Enclosure]
    published: str | None
    updated: str | None


class FeedParserRSSEntry(CommonRSSEntry):
    id: str | None
    summary: str | None
    author_detail: AuthorDetail
    published_parsed: struct_time | None
    updated_parsed: struct_time | None


class ExpandedRSSEntry(FeedParserRSSEntry):
    pubDate: struct_time | None


class FasterFeedParserRSSEntry(CommonRSSEntry):
    media_content: list[EntryContent]


type ParserRSSEntry = FeedParserRSSEntry | FasterFeedParserRSSEntry

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


class StatefulItem(TypedDict):
    state: StreamState


SentinalValue = "terminal"
Sentinal = TypedDict("Sentinal", {SentinalValue: str, "type": str})


type RSSEntry = ExpandedRSSEntry | YahooRSSEntry
type RSSParseResult = "FeedParserDict" | "FastFeedParserDict"
type DateDict = dict[str, str | int | date | bool]
type Key = str | dict[str, str]
type Hashable = int | float | str | Decimal | date | struct_time | None

# Leafs
type BasicValue = str | int
type NumLike = float | int | Decimal
type Scalar = str | int | float | Decimal
type Temporal = datetime | date | struct_time
type DateLike = str | int | datetime | date | struct_time
type SortableValue = Scalar | Temporal
type PrimitiveValue = SortableValue | None

# Geo/currency
type IPAddress = dict[str, str]
type Location = IPAddress | dict[str, float]
type CurrencyCode = Location | dict[str, int]
type AnyLocation = CurrencyCode | dict[str, float | str]

# Args
type BasicMapping = Mapping[str, BasicValue]
type BasicArg = BasicValue | BasicMapping | Sequence[BasicValue]

# Returns
type BasicDict = (
    dict[str, str]
    | dict[str, bool]
    | dict[str, int]
    | dict[str, Decimal]
    | dict[str, float]
)
type BasicList = list[str] | list[bool] | list[int] | list[Decimal] | list[float]
type BasicReturn = BasicValue | BasicDict | BasicList | tuple[BasicValue, ...]

type Stringy = str | "StringyList" | "StringyDict"
type StringyDict = dict[str, Stringy]
type StringyList = list[Stringy]

type RikoDict = (
    BasicDict
    | StringyDict
    | dict[str, PrimitiveValue]
    | dict[str, BasicDict]
    | dict[str, BasicList]
    | "DotDict[PrimitiveValue]"
)
type RikoList = BasicList | list[BasicDict] | StringyList
type RikoValue = PrimitiveValue | RikoDict | RikoList

# Instance Types
BasicValueType = (str, int)
TemporalType = (datetime, date, struct_time)
DateLikeType = (str, int, datetime, date, struct_time)
NumLikeType = (float, int, Decimal)
PrimitiveValueType = (str, int, float, Decimal, datetime, date, struct_time)
HashableType = (str, int, float, Decimal, date, struct_time)

_NONSTREAM_EXPRESSIONS = (
    ast.BinOp,
    ast.Compare,
    ast.Constant,
    ast.Dict,
    ast.DictComp,
    ast.JoinedStr,
    ast.Lambda,
    ast.List,
    ast.ListComp,
    ast.Set,
    ast.SetComp,
    ast.Tuple,
    ast.UnaryOp,
)
