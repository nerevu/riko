from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from re import RegexFlag
from typing import TYPE_CHECKING, Any, Literal, NotRequired, Required, TypedDict, Union

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.cast import CastType, LocationType, SortableCastType
    from riko.types.compile import PipeModule
    from riko.types.values import BasicValue


# Shared
type Nodes[T: (str | int)] = Sequence[T]
type Graph[T: (str | int)] = Mapping[T, Nodes[T]]
type NodeList[T: (str | int)] = list[T]
type SCC[T: (str | int)] = list[tuple[T, ...]]

type ModuleType = Literal["operator", "processor", "splitter"]

type ModuleSubtype = Literal[
    "aggregator",
    "composer",
    "source",
    "transformer",
    "splitter",
]

type ModuleSubtypes = set[ModuleSubtype]
type OperatorReturnKind = Literal["stream", "nonstream", "unknown"]
type Inference = tuple[OperatorReturnKind, str | None]


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    name: str
    type: ModuleType
    subtype: ModuleSubtype
    subtypes: ModuleSubtypes
    pollable: bool
    loopable: bool
    has_sync: bool
    has_async: bool

    def supports(self, subtype: ModuleSubtype) -> bool:
        return subtype in self.subtypes


ModuleName = Literal[
    "fetch",
    "fetchdata",
    "fetchpage",
    "forever",
    "input",
    "itembuilder",
    "loop",
    "output",
    "regex",
    "rename",
    "sort",
    "strconcat",
    "tail",
    "tokenizer",
    "truncate",
    "urlbuilder",
]


class ConfArg(TypedDict):
    type: str
    value: int | str | bool


class Terminal(TypedDict):
    terminal: str
    type: str


class Subkey(TypedDict):
    subkey: str
    type: str


Value = ConfArg | Terminal | Subkey


class Param(TypedDict):
    key: ConfArg
    value: Value


class Skip(TypedDict):
    field: str
    include: NotRequired[bool]


class ObjconfParam:
    key: str
    value: str


class ParsedParam(TypedDict):
    key: str
    value: str


class RegexRule(TypedDict):
    count: Literal[1, 0]
    default: str
    field: str
    flags: int | RegexFlag
    match: str
    offset: int
    replace: str
    series: bool


# Raw
class FetchRawConf(TypedDict):
    url: Value | list[Value]
    offline: NotRequired[Value]


class InputRawConf(TypedDict, total=False):
    name: Required[ConfArg]
    prompt: Required[ConfArg]
    type: ConfArg
    debug: ConfArg
    default: ConfArg
    test: ConfArg
    param: Param | Sequence[Param]
    position: ConfArg
    input_key: ConfArg


class SortRawRule(TypedDict, total=False):
    field: Required[Value]
    dir: Value
    type: str


class SortRawConf(TypedDict):
    rule: SortRawRule | list[SortRawRule]


class TailRawConf(TypedDict):
    count: Value


class ItemBuilderRawConf(TypedDict):
    attrs: Param | list[Param]


class RssItemBuilderRawConf(TypedDict, total=False):
    author: Value
    description: Value
    guid: Value
    link: Value
    mediaContentHeight: Value
    mediaContentType: Value
    mediaContentURL: Value
    mediaContentWidth: Value
    mediaThumbHeight: Value
    mediaThumbURL: Value
    mediaThumbWidth: Value
    pubdate: Value
    title: Value


class EmbeddedModule(TypedDict):
    id: str
    type: ModuleName
    conf: "AnyModuleRawConf"
    assign: NotRequired[ConfArg]
    emit: NotRequired[ConfArg]
    field: NotRequired[ConfArg]


class Embed(TypedDict):
    type: Literal["module"]
    value: EmbeddedModule


class LoopRawConf(TypedDict):
    count: Value
    embed: Embed
    assign: NotRequired[ConfArg]
    field: NotRequired[ConfArg]


class CountRawConf(TypedDict, total=False):
    count_key: Value


class CsvRawConf(TypedDict):
    url: Value | list[Value]
    delimiter: NotRequired[Value]
    quotechar: NotRequired[Value]
    encoding: NotRequired[Value]
    has_header: NotRequired[Value]
    skip_rows: NotRequired[Value]
    sanitize: NotRequired[Value]
    dedupe: NotRequired[Value]
    col_names: NotRequired[Value | list[Value]]
    other_sep: NotRequired[Value]


class CurrencyFormatRawConf(TypedDict, total=False):
    currency: Value


class DateFormatRawConf(TypedDict, total=False):
    format: Value


class ExchangeRateRawConf(TypedDict, total=False):
    url: Value | list[Value]
    param: Value
    currency: Value
    delay: Value
    memoize: Value
    precision: Value


class FeedAutoDiscoveryRawConf(TypedDict):
    url: Value | list[Value]
    strict: NotRequired[Value]
    sort: NotRequired[Value]


class FetchDataRawConf(TypedDict):
    url: Value | list[Value]
    path: NotRequired[Value]
    html5: NotRequired[Value]


class FetchPageRawConf(TypedDict):
    url: Value | list[Value]
    start: NotRequired[Value]
    end: NotRequired[Value]
    token: NotRequired[Value]
    detag: NotRequired[Value]


class FetchSiteFeedRawConf(TypedDict):
    url: Value | list[Value]


class FetchTableRawConf(TypedDict):
    url: Value | list[Value]
    delimiter: NotRequired[Value]
    quotechar: NotRequired[Value]
    encoding: NotRequired[Value]
    has_header: NotRequired[Value]
    skip_rows: NotRequired[Value]
    sanitize: NotRequired[Value]
    dedupe: NotRequired[Value]
    col_names: NotRequired[Value]


class FetchTextRawConf(TypedDict):
    url: Value | list[Value]
    encoding: NotRequired[Value]


class FilterRawRule(TypedDict):
    field: Value
    op: Value
    value: Value


class FilterRawConf(TypedDict):
    rule: FilterRawRule | list[FilterRawRule]
    combine: NotRequired[Value]
    permit: NotRequired[Value]
    stop: NotRequired[Value]


class GeolocateRawConf(TypedDict, total=False):
    type: Value


class JoinRawConf(TypedDict, total=False):
    join_key: Value
    other_join_key: Value
    lower: Value


class ReceiveRawConf(TypedDict):
    name: Value
    wait: NotRequired[Value]
    max_wait: NotRequired[Value]
    max_len: NotRequired[Value]


class FindRawRule(TypedDict):
    find: Value
    location: NotRequired[Value]
    param: NotRequired[Value]


class RefindRawConf(TypedDict):
    rule: FindRawRule | list[FindRawRule]


class RegexRawRule(TypedDict, total=False):
    count: Value
    default: Value
    field: Value
    flags: Value
    match: Value
    offset: Value
    replace: Value
    series: Value
    singlematch: Value
    singlelinematch: Value
    casematch: Value


class RegexRawConf(TypedDict):
    rule: RegexRawRule | list[RegexRawRule]
    multi: NotRequired[Value]
    convert: NotRequired[Value]


class RenameRawRule(TypedDict):
    field: Value
    newval: NotRequired[Value]
    copy: NotRequired[Value]


class RenameRawConf(TypedDict):
    rule: RenameRawRule | list[RenameRawRule]


class SendRawConf(TypedDict):
    name: Value


class SimpleMathRawConf(TypedDict):
    other: Value
    op: Value


class SlugifyRawConf(TypedDict, total=False):
    separator: Value


class SplitRawConf(TypedDict, total=False):
    splits: Value


class StrconcatRawConf(TypedDict):
    part: Value | list[Value]


class StrfindRawConf(TypedDict):
    rule: FindRawRule | list[FindRawRule]


class StrReplaceRawRule(TypedDict):
    find: Value
    replace: Value
    param: NotRequired[Value]


class StrReplaceRawConf(TypedDict):
    rule: StrReplaceRawRule | list[StrReplaceRawRule]


class StrTransformRawRule(TypedDict):
    transform: Value
    args: NotRequired[Value]


class StrTransformRawConf(TypedDict):
    rule: StrTransformRawRule | list[StrTransformRawRule]


class SubelementRawConf(TypedDict):
    path: Value
    token_key: NotRequired[Value]


class SubstrRawConf(TypedDict, total=False):
    start: Value
    length: Value


class SumRawConf(TypedDict, total=False):
    sum_key: Value
    group_key: Value


class TimeoutRawConf(TypedDict, total=False):
    days: Value
    seconds: Value
    microseconds: Value
    milliseconds: Value
    minutes: Value
    hours: Value
    weeks: Value


class TokenizerRawConf(TypedDict, total=False):
    delimiter: Value
    dedupe: Value
    sort: Value
    token_key: Value


class TruncateRawConf(TypedDict, total=False):
    count: Value
    start: Value


class TypecastRawConf(TypedDict, total=False):
    type: Value


class UniqRawConf(TypedDict, total=False):
    uniq_key: Value
    limit: Value


class UrlBuilderRawConf(TypedDict, total=False):
    base: Value
    ext: Value
    path: Value | list[Value]
    param: Param | list[Param]


class UrlParseRawConf(TypedDict, total=False):
    parse_key: Value


class XpathFetchPageRawConf(TypedDict):
    url: Value | list[Value]
    xpath: NotRequired[Value]
    html5: NotRequired[Value]


type AnyModuleRawConf = (
    CountRawConf
    | CsvRawConf
    | CurrencyFormatRawConf
    | DateFormatRawConf
    | ExchangeRateRawConf
    | FeedAutoDiscoveryRawConf
    | FetchRawConf
    | FetchDataRawConf
    | FetchPageRawConf
    | FetchSiteFeedRawConf
    | FetchTableRawConf
    | FetchTextRawConf
    | FilterRawConf
    | GeolocateRawConf
    | InputRawConf
    | ItemBuilderRawConf
    | JoinRawConf
    | LoopRawConf
    | ReceiveRawConf
    | RefindRawConf
    | RegexRawConf
    | RenameRawConf
    | RssItemBuilderRawConf
    | SendRawConf
    | SimpleMathRawConf
    | SlugifyRawConf
    | SortRawConf
    | SplitRawConf
    | StrconcatRawConf
    | StrfindRawConf
    | StrReplaceRawConf
    | StrTransformRawConf
    | SubelementRawConf
    | SubstrRawConf
    | SumRawConf
    | TailRawConf
    | TimeoutRawConf
    | TokenizerRawConf
    | TruncateRawConf
    | TypecastRawConf
    # | UdfRawConf
    | UniqRawConf
    | UrlBuilderRawConf
    | UrlParseRawConf
    | XpathFetchPageRawConf
)


# Parsed
# Rules
@dataclass
class FilterConfRule:
    field: str
    op: Literal[
        "contains",
        "doesnotcontain",
        "matches",
        "is",
        "isnot",
        "truthy",
        "falsy",
        "greater",
        "less",
        "after",
        "before",
        "atleast",
        "atmost",
    ]
    value: "BasicValue"


@dataclass
class SortConfRule:
    field: str = "content"
    dir: Literal["asc", "desc"] = "asc"
    cast: bool = False  # Not implemented
    type: Union["SortableCastType", None] = None


@dataclass
class RegexConfRule:
    field: str
    match: str
    default: str | None = None
    casematch: bool | None = None
    singlelinematch: bool | None = None
    singlematch: bool | None = None
    offset: int = 0
    seriesmatch: bool = True
    replace: str = ""


@dataclass
class FindConfRule:
    find: str
    location: Literal["before", "after", "at"] = "before"
    param: Literal["first", "last"] = "first"


@dataclass
class RenameConfRule:
    field: str
    newval: str | None = None
    copy: bool = False


@dataclass
class StrReplaceConfRule:
    find: str
    replace: str
    param: Literal["first", "last", "every"] = "every"


@dataclass
class StrTransformConfRule:
    transform: Literal[
        "capitalize",
        "lower",
        "upper",
        "swapcase",
        "title",
        "strip",
        "rstrip",
        "lstrip",
        "zfill",
        "replace",
        "count",
        "find",
    ]
    args: str = ""


# Confs
class SortConf(TypedDict):
    rule: SortConfRule | list[SortConfRule]


class InputConf(TypedDict, total=False):
    prompt: Required[str]
    type: Required["CastType"]
    default: str
    test: bool
    input_key: str


class FetchConf(TypedDict, total=False):
    url: str
    delay: int


class TailConf(TypedDict):
    count: int


class ItemBuilderConf(TypedDict):
    attrs: ParsedParam | Sequence[ParsedParam]


class RssItemBuilderConf(TypedDict, total=False):
    author: str
    description: str
    guid: str
    link: str
    mediaContentHeight: str
    mediaContentType: str
    mediaContentURL: str
    mediaContentWidth: str
    mediaThumbHeight: str
    mediaThumbURL: str
    mediaThumbWidth: str
    pubDate: str
    title: str


class LoopConf(TypedDict):
    count: str
    assign: str
    embed: EmbeddedModule
    field: str


class AggregateConf(TypedDict):
    func: Callable[..., Any]


class CountConf(TypedDict, total=False):
    count_key: str | None


class CsvConf(TypedDict):
    url: str
    encoding: str
    col_names: NotRequired[Sequence[str] | None]
    delimiter: str = ","
    quotechar: str = '"'
    has_header: bool = True
    skip_rows: int = 0
    dedupe: bool = True
    sanitize: bool = False


class CurrencyFormatConf(TypedDict):
    currency: str = "USD"


class DateFormatConf(TypedDict):
    format: str = "%m/%d/%Y %H:%M:%S"


class ExchangeRateConf(TypedDict):
    url: str
    param: ParsedParam | Sequence[ParsedParam]
    currency: str = "USD"
    delay: int = 0
    memoize: bool = True
    precision: int = 6


class FeedAutoDiscoveryConf(TypedDict):
    url: str
    strict: bool = True
    sort: bool = False


class FetchDataConf(TypedDict):
    url: str
    path: NotRequired[str]
    html5: NotRequired[bool]


class FetchPageConf(TypedDict):
    url: str
    start: NotRequired[str]
    end: NotRequired[str]
    token: NotRequired[str]
    detag: bool = False


class FetchSiteFeedConf(TypedDict):
    url: str


class FetchTableConf(CsvConf):
    sanitize: bool = True


class FetchTextConf(TypedDict):
    url: str
    encoding: str


class FilterConf(TypedDict):
    rule: FilterConfRule | list[FilterConfRule]
    combine: Literal["and", "or"] = "and"
    permit: bool = True
    stop: bool = False


class GeolocateConf(TypedDict):
    type: "LocationType"


class JoinConf(TypedDict, total=False):
    join_key: str | None
    other_join_key: str
    lower: bool


class ReceiveConf(TypedDict, total=False):
    name: str
    wait: int | float = 0.1
    max_wait: int | float = 5
    max_len: int


class RefindConf(TypedDict):
    rule: FindConfRule | list[FindConfRule]


class RegexConf(TypedDict, total=False):
    rule: Required[RegexConfRule | list[RegexConfRule]]
    multi: bool = False
    convert: bool = True


class RenameConf(TypedDict):
    rule: RenameConfRule | list[RenameConfRule]


class SendConf(TypedDict):
    name: str


class SimpleMathConf(TypedDict):
    other: int | float
    op: Literal[
        "add", "subtract", "multiply", "divide", "floor", "modulo", "power", "mean"
    ]


class SlugifyConf(TypedDict):
    separator: str = "-"


class SplitConf(TypedDict):
    splits: int = 2


class StrconcatConf(TypedDict):
    part: str | Subkey | Terminal | list[str | Subkey | Terminal]


class StrfindConf(TypedDict):
    rule: FindConfRule | list[FindConfRule]


class StrReplaceConf(TypedDict):
    rule: StrReplaceConfRule | list[StrReplaceConfRule]


class StrTransformConf(TypedDict):
    rule: StrTransformConfRule | list[StrTransformConfRule]


class SubelementConf(TypedDict):
    path: str
    token_key: str = "content"  # noqa: S105


class SubstrConf(TypedDict):
    start: int = 0
    length: int = 0


class SumConf(TypedDict):
    sum_key: str = "content"
    group_key: str | None = None


class TimeoutConf(TypedDict, total=False):
    days: int
    seconds: int
    microseconds: int
    milliseconds: int
    minutes: int
    hours: int
    weeks: int


class TokenizerConf(TypedDict):
    delimiter: str = ","
    dedupe: bool = False
    sort: bool = False
    token_key: str = "content"  # noqa: S105


class TruncateConf(TypedDict):
    count: int = 0
    start: int = 0


class TypecastConf(TypedDict):
    type: "CastType"


class UdfConf(TypedDict):
    func: Callable[..., Any]


class UrlBuilderConf(TypedDict, total=False):
    base: str
    ext: str
    path: str
    param: ParsedParam | list[ParsedParam]


class UrlParseConf(TypedDict):
    parse_key: str = "content"


class XpathFetchPageConf(TypedDict):
    url: str
    xpath: NotRequired[str]
    html5: bool = False


# General
type ConfDictValues = "PipeModule" | ParsedParam

type RawConfValues = dict[str, str | int | bool]


type ConfValues = (
    "BasicValue"
    | ConfDictValues
    | bool
    | DataclassInstance
    | int
    | Literal["and", "or"]
    | list[ParsedParam]
    | list[str]
    | str
)

type AnyConfRule = (
    FindConfRule
    | FilterConfRule
    | RegexConfRule
    | RenameConfRule
    | SortConfRule
    | StrReplaceConfRule
    | StrTransformConfRule
)

type AnyModuleConf = (
    AggregateConf
    | CountConf
    | CsvConf
    | CurrencyFormatConf
    | DateFormatConf
    | ExchangeRateConf
    | FeedAutoDiscoveryConf
    | FetchConf
    | FetchDataConf
    | FetchPageConf
    | FetchSiteFeedConf
    | FetchTableConf
    | FetchTextConf
    | FilterConf
    | GeolocateConf
    | InputConf
    | ItemBuilderConf
    | JoinConf
    | LoopConf
    | ReceiveConf
    | RefindConf
    | RegexConf
    | RenameConf
    | RssItemBuilderConf
    | SendConf
    | SimpleMathConf
    | SlugifyConf
    | SortConf
    | SplitConf
    | StrconcatConf
    | StrfindConf
    | StrReplaceConf
    | StrTransformConf
    | SubelementConf
    | SubstrConf
    | SumConf
    | TailConf
    | TimeoutConf
    | TokenizerConf
    | TruncateConf
    | TypecastConf
    | UdfConf
    | UrlBuilderConf
    | UrlParseConf
    | XpathFetchPageConf
)
