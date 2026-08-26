import ast
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum, auto
from pathlib import PurePath
from time import struct_time
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

if TYPE_CHECKING:
    from fastfeedparser import FastFeedParserDict
    from feedparser import FeedParserDict

    from riko.dotdict import DotDict


# Misc
class MissingType:
    def __repr__(self) -> str:
        return "<MISSING>"


MISSING = MissingType()


class StreamState(Enum):
    PENDING = auto()
    DONE = auto()


class ModuleName(StrEnum):
    """A type-safe module name."""


class TargetName(StrEnum):
    """A type-safe target name."""


class EntryContent(TypedDict, total=False):
    value: Required[str]
    type: str
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


class CommonRSSEntry(TypedDict, total=False):
    link: Required[str]
    author: str | None
    title: str | None
    description: str | None
    content: list[EntryContent]
    enclosures: list[Enclosure]
    published: str | None
    updated: str | None


class FeedParserRSSEntry(CommonRSSEntry, total=False):
    id: str | None
    summary: str | None
    author_detail: AuthorDetail
    published_parsed: struct_time | None
    updated_parsed: struct_time | None


class ExpandedRSSEntry(FeedParserRSSEntry):
    pubDate: struct_time | None


class FasterFeedParserRSSEntry(CommonRSSEntry, total=False):
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


class Sentinal(TypedDict):
    terminal: str
    type: str
    path: NotRequired[str]


SentinalValue: str = "terminal"

type RSSEntry = ExpandedRSSEntry | YahooRSSEntry
type RSSParseResult = "FeedParserDict" | "FastFeedParserDict"
type DateDict = dict[str, str | int | date | bool]
type Key = str | dict[str, str]
type Hashable = int | float | str | Decimal | date | struct_time | None
type Inputs = Mapping[str, str | int | bool]

# Leafs
type BasicValue = str | int
type NumLike = float | int | Decimal
type Scalar = str | int | float | Decimal
type Temporal = datetime | date | struct_time
type DateLike = str | int | datetime | date | struct_time
type SortableValue = Scalar | Temporal
type PrimitiveValue = SortableValue | None
type ModuleNameLike = str | ModuleName
type TargetLike = str | TargetName


# Geo/currency
class Region(TypedDict, total=False):
    code_2: Required[str]
    code_3: str
    continent: Required[str]
    country: str
    num: str


class CurrencyCode(TypedDict, total=False):
    code: Required[str]
    location: Required[str]
    name: str
    name_plural: str
    symbol: str
    symbol_native: str
    locale: str


type IPAddress = dict[str, str]
type Location = IPAddress | dict[str, float]
type AnyLocation = Region | CurrencyCode | Location | dict[str, float | str]

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
BasicValueType: tuple[type, ...] = (str, int)
TemporalType: tuple[type, ...] = (datetime, date, struct_time)
DateLikeType: tuple[type, ...] = (str, int, datetime, date, struct_time)
NumLikeType: tuple[type, ...] = (float, int, Decimal)
PrimitiveValueType: tuple[type, ...] = (
    str,
    int,
    float,
    Decimal,
    datetime,
    date,
    struct_time,
)
HashableType: tuple[type, ...] = (
    str,
    int,
    float,
    Decimal,
    date,
    struct_time,
    PurePath,
)

NonstreamExpressions: tuple[type, ...] = (
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
