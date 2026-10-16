"""Static config contracts for the built-in modules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Literal, NotRequired, Required, TypedDict

import attrs
from attrs import define

from riko.base._config import BUILTIN_PROVIDER

from ._collections import (
    FrozenConf,
    require_from_form,
    require_from_typed_dict,
    require_instance,
    serialize_attrs,
    validator_from_require,
)
from ._pipedef import CountValues, Embed

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from re import Pattern, RegexFlag

    from ._collections import TypeRequire
    from ._enums import CastType, ExecutionMode, FmtLike, LocationType, SortableCastType
    from ._io import PathLike
    from ._scalars import BasicValue
    from ._values import Inputs


# Shared
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


def get_module_provider(name: str) -> str:
    """
    Gets the provider/namespace a module name belongs to.

    Args:

        name: The module name.

    Returns:

        The first dotted segment of a qualified name, or ``"riko"`` (the built-in
        provider) for an unqualified name.

    Examples:

        >>> get_module_provider("fetch")
        'riko'
        >>> get_module_provider("example.lookup")
        'example'
        >>> get_module_provider("microsoft.autopilot.ensure")
        'microsoft'

    """
    prefix, dot, _ = name.partition(".")
    return prefix if dot else BUILTIN_PROVIDER


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

    @property
    def provider(self) -> str:
        """
        The module's namespace.

        The first dotted segment of its name, or the built-in provider for an
        unqualified name.
        """
        return get_module_provider(self.name)

    def supports(self, subtype: ModuleSubtype) -> bool:
        return subtype in self.subtypes


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
    default: Value


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
    locale: Value
    clean: Value


class DateFormatRawConf(TypedDict, total=False):
    format: Value
    timezone: Value


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
    normalize_key: Value


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
    value: BasicValue


@dataclass
class SortConfRule:
    field: str = "content"
    dir: Literal["asc", "desc"] = "asc"
    cast: bool = False  # Not implemented
    type: SortableCastType | None = None
    default: BasicValue | None = None


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
    args: BasicValue | Sequence[BasicValue] = ""


# Confs
class SortConf(TypedDict):
    rule: NotRequired[SortConfRule | list[SortConfRule]]


class InputConf(TypedDict, total=False):
    type: CastType
    prompt: str
    default: str
    test: bool
    input_key: str


class FetchConf(TypedDict, total=False):
    url: str
    encoding: str


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
    func: Callable


class CountConf(TypedDict, total=False):
    count_key: str | None


class CsvConf(TypedDict, total=False):
    url: Required[str]
    encoding: str
    col_names: NotRequired[Sequence[str] | None]
    delimiter: str
    quotechar: str
    has_header: bool
    skip_rows: int
    dedupe: bool
    sanitize: bool


class CurrencyFormatConf(TypedDict, total=False):
    currency: str
    locale: str
    clean: bool


class DateFormatConf(TypedDict, total=False):
    format: str


class ExchangeRateConf(TypedDict, total=False):
    url: str
    param: dict[str, str]
    currency: str
    encoding: str
    memoize: bool
    precision: int


class FeedAutoDiscoveryConf(TypedDict, total=False):
    url: Required[str]
    strict: bool
    sort: bool


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
    detag: bool


class FetchSiteFeedConf(TypedDict):
    url: str


class FetchTableConf(CsvConf, total=False):
    sanitize: bool


class FetchTextConf(TypedDict, total=False):
    url: Required[str]
    encoding: str


class FilterConf(TypedDict, total=False):
    rule: Required[FilterConfRule | list[FilterConfRule]]
    combine: Literal["and", "or"]
    permit: NotRequired[bool]
    stop: NotRequired[bool]


class GeolocateConf(TypedDict):
    type: NotRequired[LocationType]


class JoinConf(TypedDict, total=False):
    join_key: str | None
    other_join_key: str
    lower: bool


class ReceiveConf(TypedDict, total=False):
    name: str
    wait: int | float
    max_wait: int | float
    max_len: int


class RefindConf(TypedDict):
    rule: FindConfRule | list[FindConfRule]


class RegexConf(TypedDict, total=False):
    rule: Required[RegexConfRule | list[RegexConfRule]]
    multi: bool


class RenameConf(TypedDict):
    rule: RenameConfRule | list[RenameConfRule]


class SendConf(TypedDict, total=False):
    max_wait: int | float


class SimpleMathConf(TypedDict):
    other: int | float
    op: Literal[
        "add", "subtract", "multiply", "divide", "floor", "modulo", "power", "mean"
    ]


class SlugifyConf(TypedDict, total=False):
    separator: str


class SplitConf(TypedDict, total=False):
    splits: int


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
    token_key: str | None


class SubstrConf(TypedDict, total=False):
    start: int
    length: int


class SumConf(TypedDict, total=False):
    sum_key: str
    group_key: str | None


class TimeoutConf(TypedDict, total=False):
    days: int
    seconds: int
    microseconds: int
    milliseconds: int
    minutes: int
    hours: int
    weeks: int


class TokenizerConf(TypedDict, total=False):
    delimiter: str
    dedupe: bool
    sort: bool
    token_key: str  # noqa: S105


class TruncateConf(TypedDict, total=False):
    count: int
    start: int


class TypecastConf(TypedDict):
    type: NotRequired[CastType]


class UdfConf(TypedDict):
    func: Callable


class UniqConf(TypedDict, total=False):
    uniq_key: str
    limit: int


class UrlBuilderConf(TypedDict, total=False):
    base: str
    ext: str
    path: str
    param: ParsedParam | list[ParsedParam]


class UrlParseConf(TypedDict, total=False):
    normalize_key: str


class WriteConf(TypedDict, total=False):
    dest: PathLike
    fmt: FmtLike | None
    mode: str


class XpathFetchPageConf(TypedDict, total=False):
    url: Required[str]
    xpath: str
    encoding: str
    html5: bool


# General
type OptionValues = bool | str | CountValues

type ConfValues = (
    BasicValue
    | ParsedParam
    | bool
    | float
    | int
    | Literal["and", "or"]
    | list[ParsedParam]
    | list[str]
    | str
    | None
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

type Conf = AnyModuleConf | AnyModuleRawConf
type MaybeFrozenConf = Conf | FrozenConf

require_module_conf: TypeRequire[object, AnyModuleConf] = require_from_form(
    AnyModuleConf
)
require_conf: TypeRequire[object, Conf] = require_from_form(Conf)


class RawCallOptions(TypedDict, total=False):
    """Call options forwarded to a module callable, as keyword arguments."""

    emit: bool
    assign: str
    field: str
    count: CountValues


type CallOptionsLike = CallOptions | RawCallOptions | Mapping[str, OptionValues]

_is_optional_bool = validator_from_require(require_instance, bool, optional=True)
_is_optional_str = validator_from_require(require_instance, str, optional=True)
_require_count = require_from_form(CountValues)
_is_optional_count = validator_from_require(_require_count, optional=True)
_item, _what = RawCallOptions, "call options"
build_require_raw_call_options: Callable[
    ..., TypeRequire[Mapping[str, object], RawCallOptions]
] = partial(require_from_typed_dict, _item, _what)
_require_raw_call_options = build_require_raw_call_options()


@define(frozen=True, slots=True, kw_only=True, repr=False)
class CallOptions:
    """
    Call options forwarded to a module callable alongside its configuration.

    Attributes:

        emit: Whether to yield the result as a new item rather than assign it.
        assign: The item field the result is assigned to.
        field: The item field whose value the module receives.
        count: Whether to keep the first result or all of them.

    Examples:

        >>> options = CallOptions.from_raw({"field": "title", "emit": True})
        >>> options
        CallOptions(emit=True, field='title')
        >>> options.field, options.assign
        ('title', None)
        >>> options.kwargs
        {'emit': True, 'field': 'title'}

    """

    emit: bool | None = attrs.field(default=None, validator=_is_optional_bool)
    assign: str | None = attrs.field(default=None, validator=_is_optional_str)
    field: str | None = attrs.field(default=None, validator=_is_optional_str)
    count: CountValues | None = attrs.field(default=None, validator=_is_optional_count)

    @classmethod
    def from_raw(
        cls, raw: CallOptionsLike | None = None, what: str | None = None
    ) -> CallOptions:
        """
        Builds call options from keyword-argument form.

        Args:

            raw: The options to convert or return as is. ``None`` means no options.
            what: The name used in error messages (default: "call options").

        Returns:

            The call options.

        Raises:

            InvalidPipelineError: If ``raw`` has a key that is not a call option, or
                an option value of the wrong type.

        """
        if raw is None:
            options = cls()
        elif isinstance(raw, CallOptions):
            options = raw
        else:
            options = cls(**_require_raw_call_options(raw, what))

        return options

    @property
    def kwargs(self) -> RawCallOptions:
        """The set options as fresh keyword arguments."""
        return _require_raw_call_options(serialize_attrs(self))

    def __repr__(self) -> str:
        pairs = ", ".join(f"{key}={value!r}" for key, value in self.kwargs.items())
        return f"CallOptions({pairs})"


class ContextOverrides(TypedDict, total=False):
    """The per-call overrides a pipe call applies to its ``Context``."""

    mode: ExecutionMode
    inputs: Inputs
    test: bool


__all__ = [
    "AggregateConf",
    "AnyConfRule",
    "AnyModuleConf",
    "CallOptions",
    "CallOptionsLike",
    "ContextOverrides",
    "CountConf",
    "CsvConf",
    "CurrencyFormatConf",
    "DateFormatConf",
    "Embed",
    "ExchangeRateConf",
    "FeedAutoDiscoveryConf",
    "FetchConf",
    "FetchDataConf",
    "FetchPageConf",
    "FetchSiteFeedConf",
    "FetchTableConf",
    "FetchTextConf",
    "FilterConf",
    "FilterConfRule",
    "FindConfRule",
    "GeolocateConf",
    "InputConf",
    "ItemBuilderConf",
    "JoinConf",
    "MaybeFrozenConf",
    "ModuleCategory",
    "ModuleClass",
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleSubtypes",
    "ModuleType",
    "ParsedParam",
    "RawCallOptions",
    "ReceiveConf",
    "RefindConf",
    "RegexConf",
    "RegexConfRule",
    "RenameConf",
    "RenameConfRule",
    "RssItemBuilderConf",
    "SendConf",
    "SimpleMathConf",
    "SlugifyConf",
    "SortConf",
    "SortConfRule",
    "SplitConf",
    "StrReplaceConf",
    "StrReplaceConfRule",
    "StrTransformConf",
    "StrTransformConfRule",
    "StrconcatConf",
    "StrfindConf",
    "SubelementConf",
    "Subkey",
    "SubstrConf",
    "SumConf",
    "TailConf",
    "Terminal",
    "TimeoutConf",
    "TokenizerConf",
    "TruncateConf",
    "TypecastConf",
    "UdfConf",
    "UniqConf",
    "UrlBuilderConf",
    "UrlParseConf",
    "WriteConf",
    "XpathFetchPageConf",
    "get_module_provider",
]
