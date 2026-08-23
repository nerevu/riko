from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from re import Pattern, RegexFlag
from typing import (
    TYPE_CHECKING,
    Literal,
    NewType,
    NotRequired,
    Required,
    TypedDict,
    Union,
)

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.cast import CastType, LocationType, SortableCastType
    from riko.types._module_ids import LoopableModuleId, ModuleId
    from riko.types.compile import PipeModule
    from riko.types.general import Function
    from riko.types.values import BasicValue, TargetLike


# Shared
type Nodes[T: (str | int)] = Sequence[T]
type Graph[T: (str | int)] = Mapping[T, Nodes[T]]
type NodeList[T: (str | int)] = list[T]
type SCC[T: (str | int)] = list[tuple[T, ...]]

type ModuleType = Literal["operator", "processor", "splitter"]
type ModuleCategory = Literal["sink", "source", "transform"]
type ModuleClass = Literal["Sinks", "Sources", "Transforms"]

type ModuleSubtype = Literal[
    "aggregator", "composer", "source", "transformer", "splitter"
]

type ModuleSubtypes = set[ModuleSubtype]


class OperatorReturnKind(StrEnum):
    STREAM = "stream"
    NONSTREAM = "nonstream"
    UNKNOWN = "unknown"


type Inference = tuple[OperatorReturnKind, str | None]


class InferenceSource(StrEnum):
    ANNOTATION = "annotation"
    GENERATOR = "generator"
    AST = "ast"


@dataclass(frozen=True, slots=True)
class ReturnInference:
    kind: OperatorReturnKind
    source: InferenceSource | None
    reason: str = ""


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


PipeId = NewType("PipeId", str)

CountValues = Literal["first", "all"]


class ConfArg(TypedDict):
    type: str
    value: int | str | bool


class Terminal(TypedDict):
    terminal: str
    type: str
    path: NotRequired[str]


class Subkey(TypedDict):
    subkey: str
    type: str


Value = ConfArg | Terminal | Subkey


class Param(TypedDict):
    key: ConfArg
    value: Value


class Skip(TypedDict, total=False):
    field: Required[str]
    text: str
    op: Literal["intersection", "contains", "search"]
    include: bool


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
    match: Pattern[str]
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
    singlelinematch: Value
    casematch: Value


class RegexRawConf(TypedDict):
    rule: RegexRawRule | list[RegexRawRule]
    multi: NotRequired[Value]


class RenameRawRule(TypedDict):
    field: Value
    newval: NotRequired[Value]
    copy: NotRequired[Value]


class RenameRawConf(TypedDict):
    rule: RenameRawRule | list[RenameRawRule]


class SendRawConf(TypedDict):
    max_wait: NotRequired[Value]


class SimpleMathRawConf(TypedDict):
    other: Value
    op: Value


class SlugifyRawConf(TypedDict, total=False):
    separator: Value


class SplitRawConf(TypedDict, total=False):
    splits: ConfArg


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


class SubModuleRawConf(TypedDict):
    gid: Value


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
    | SubModuleRawConf
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


class EmbedRef(TypedDict):
    id: str
    type: Union["ModuleId", "PipeId", Literal["output"]]


class LoopableEmbedRef(TypedDict):
    id: str
    type: "LoopableModuleId | PipeId"


class EmbeddedModule(EmbedRef, total=False):
    """
    A loop's embedded submodule hoisted to a standalone ``{id, type, conf}``
    descriptor for code generation. Built by ``compile.gen_modules(embedded=True)``
    from the loop's compact top-level ``embed`` plus its ``conf``.
    """

    conf: Required[AnyModuleRawConf]
    emit: ConfArg
    assign: ConfArg
    field: ConfArg


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
    args: "BasicValue | Sequence[BasicValue]" = ""


# Confs
class SortConf(TypedDict):
    rule: NotRequired[SortConfRule | list[SortConfRule]]


class InputConf(TypedDict, total=False):
    type: "CastType"
    prompt: str
    default: str
    test: bool
    input_key: str


class FetchConf(TypedDict, total=False):
    url: str
    encoding: str = "utf-8"


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


class AggregateConf(TypedDict):
    func: "Function"


class CountConf(TypedDict, total=False):
    count_key: str | None


class CsvConf(TypedDict, total=False):
    url: Required[str]
    encoding: str = "utf-8"
    col_names: NotRequired[Sequence[str] | None]
    delimiter: str = ","
    quotechar: str = '"'
    has_header: bool = True
    skip_rows: int = 0
    dedupe: bool = True
    sanitize: bool = False


class CurrencyFormatConf(TypedDict, total=False):
    currency: str = "USD"


class DateFormatConf(TypedDict, total=False):
    format: str = "%m/%d/%Y %H:%M:%S"


class ExchangeRateConf(TypedDict, total=False):
    url: str
    param: dict[str, str]
    currency: str = "USD"
    encoding: str = "utf-8"
    memoize: bool = True
    precision: int = 6


class FeedAutoDiscoveryConf(TypedDict, total=False):
    url: Required[str]
    strict: bool = True
    sort: bool = False


class FetchDataConf(TypedDict):
    url: str
    encoding: NotRequired[str]
    path: NotRequired[str]
    html5: NotRequired[bool]


class FetchPageConf(TypedDict, total=False):
    url: Required[str]
    encoding: NotRequired[str]
    start: NotRequired[str]
    end: NotRequired[str]
    token: NotRequired[str]
    detag: bool = False


class FetchSiteFeedConf(TypedDict):
    url: str


class FetchTableConf(CsvConf, total=False):
    sanitize: bool = True


class FetchTextConf(TypedDict, total=False):
    url: Required[str]
    encoding: str = "utf-8"


class FilterConf(TypedDict, total=False):
    rule: Required[FilterConfRule | list[FilterConfRule]]
    combine: Literal["and", "or"] = "and"
    permit: NotRequired[bool] = True
    stop: NotRequired[bool] = False


class GeolocateConf(TypedDict):
    type: NotRequired["LocationType"]


class JoinConf(TypedDict, total=False):
    join_key: str | None
    other_join_key: str
    lower: bool


class ReceiveConf(TypedDict, total=False):
    name: str
    wait: int | float = 1
    max_wait: int | float = 5
    max_len: int


class RefindConf(TypedDict):
    rule: FindConfRule | list[FindConfRule]


class RegexConf(TypedDict, total=False):
    rule: Required[RegexConfRule | list[RegexConfRule]]
    multi: bool = False


class RenameConf(TypedDict):
    rule: RenameConfRule | list[RenameConfRule]


class SendConf(TypedDict, total=False):
    max_wait: int | float = 5


class SimpleMathConf(TypedDict):
    other: int | float
    op: Literal[
        "add", "subtract", "multiply", "divide", "floor", "modulo", "power", "mean"
    ]


class SlugifyConf(TypedDict, total=False):
    separator: str = "-"


class SplitConf(TypedDict, total=False):
    splits: int = 2


class StrconcatConf(TypedDict):
    part: str | Subkey | Terminal | Sequence[str | Subkey | Terminal]


class StrfindConf(TypedDict):
    rule: FindConfRule | list[FindConfRule]


class StrReplaceConf(TypedDict):
    rule: StrReplaceConfRule | list[StrReplaceConfRule]


class StrTransformConf(TypedDict):
    rule: StrTransformConfRule | list[StrTransformConfRule]


class SubelementConf(TypedDict, total=False):
    path: Required[str]
    token_key: str | None = "content"  # noqa: S105


class SubstrConf(TypedDict, total=False):
    start: int = 0
    length: int = 0


class SumConf(TypedDict, total=False):
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


class TokenizerConf(TypedDict, total=False):
    delimiter: str = ","
    dedupe: bool = False
    sort: bool = False
    token_key: str = "content"  # noqa: S105


class TruncateConf(TypedDict, total=False):
    count: int = 0
    start: int = 0


class TypecastConf(TypedDict):
    type: NotRequired["CastType"]


class UdfConf(TypedDict):
    func: "Function"


class UniqConf(TypedDict, total=False):
    uniq_key: str = "content"
    limit: int = 1024


class UrlBuilderConf(TypedDict, total=False):
    base: str
    ext: str
    path: str
    param: ParsedParam | list[ParsedParam]


class UrlParseConf(TypedDict, total=False):
    parse_key: str = "content"


class WriteConf(TypedDict, total=False):
    url: Required[str | Path]
    target: "TargetLike | None" = None
    mode: str = "wb+"


class XpathFetchPageConf(TypedDict, total=False):
    url: Required[str]
    xpath: str
    encoding: str = "utf-8"
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
    | UniqConf
    | UrlBuilderConf
    | UrlParseConf
    | WriteConf
    | XpathFetchPageConf
)
