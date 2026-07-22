# vim: sw=4:ts=4:expandtab
"""
riko.types.configs
~~~~~~~~~~~~~~~~~~~
Parse-time ``objconf`` config types, one per module. Each subclasses
``DynamicConf`` (case-insensitive attribute + mapping access; missing keys return
``None``). Field types only — the ``conf=`` contract and its defaults live on the
``<Name>Conf`` TypedDicts in ``riko.types.modules``; runtime defaults come from each
module's ``DEFAULTS``.

Generated from the nonraw ``<Name>Conf`` TypedDicts by ``riko.cli.gen_config``.
Edit those objects (not this file), then regenerate with ``gen-config``.
``tests/internal/test_gen_config.py`` fails if the two layers drift.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

from riko import DynamicConf

if TYPE_CHECKING:
    from riko.cast import CastType, LocationType
    from riko.types.modules import (
        EmbeddedModule,
        FilterConfRule,
        FindConfRule,
        ParsedParam,
        RegexConfRule,
        RenameConfRule,
        SortConfRule,
        StrReplaceConfRule,
        StrTransformConfRule,
        Subkey,
        Terminal,
    )


class SortObjconf(DynamicConf):
    rule: SortConfRule | list[SortConfRule]


class InputObjconf(DynamicConf):
    prompt: str
    type: CastType
    default: str
    test: bool
    input_key: str


class FetchObjconf(DynamicConf):
    url: str
    delay: int


class TailObjconf(DynamicConf):
    count: int


class ItemBuilderObjconf(DynamicConf):
    attrs: ParsedParam | Sequence[ParsedParam]


class RssItemBuilderObjconf(DynamicConf):
    author: str
    description: str
    guid: str
    link: str
    mediaContentHeight: str  # noqa: N815
    mediaContentType: str  # noqa: N815
    mediaContentURL: str  # noqa: N815
    mediaContentWidth: str  # noqa: N815
    mediaThumbHeight: str  # noqa: N815
    mediaThumbURL: str  # noqa: N815
    mediaThumbWidth: str  # noqa: N815
    pubDate: str  # noqa: N815
    title: str


class LoopObjconf(DynamicConf):
    count: str
    assign: str
    embed: EmbeddedModule
    field: str


class AggregateObjconf(DynamicConf):
    func: Callable[..., Any]


class CountObjconf(DynamicConf):
    count_key: str | None


class CsvObjconf(DynamicConf):
    url: str
    encoding: str
    col_names: Sequence[str] | None
    delimiter: str
    quotechar: str
    has_header: bool
    skip_rows: int
    dedupe: bool
    sanitize: bool


class CurrencyFormatObjconf(DynamicConf):
    currency: str


class DateFormatObjconf(DynamicConf):
    format: str


class ExchangeRateObjconf(DynamicConf):
    url: str
    param: dict[str, str]
    currency: str
    delay: int
    memoize: bool
    precision: int


class FeedAutoDiscoveryObjconf(DynamicConf):
    url: str
    strict: bool
    sort: bool


class FetchDataObjconf(DynamicConf):
    url: str
    path: str
    html5: bool


class FetchPageObjconf(DynamicConf):
    url: str
    start: str
    end: str
    token: str
    detag: bool


class FetchSiteFeedObjconf(DynamicConf):
    url: str


class FetchTableObjconf(CsvObjconf):
    sanitize: bool


class FetchTextObjconf(DynamicConf):
    url: str
    encoding: str


class FilterObjconf(DynamicConf):
    rule: FilterConfRule | list[FilterConfRule]
    combine: Literal["and", "or"]
    permit: bool
    stop: bool


class GeolocateObjconf(DynamicConf):
    type: LocationType


class JoinObjconf(DynamicConf):
    join_key: str | None
    other_join_key: str
    lower: bool


class ReceiveObjconf(DynamicConf):
    name: str
    wait: int | float
    max_wait: int | float
    max_len: int


class RefindObjconf(DynamicConf):
    rule: FindConfRule | list[FindConfRule]


class RegexObjconf(DynamicConf):
    rule: RegexConfRule | list[RegexConfRule]
    multi: bool
    convert: bool


class RenameObjconf(DynamicConf):
    rule: RenameConfRule | list[RenameConfRule]


class SendObjconf(DynamicConf):
    name: str


class SimpleMathObjconf(DynamicConf):
    other: int | float
    op: Literal[
        "add", "subtract", "multiply", "divide", "floor", "modulo", "power", "mean"
    ]


class SlugifyObjconf(DynamicConf):
    separator: str


class SplitObjconf(DynamicConf):
    splits: int


class StrconcatObjconf(DynamicConf):
    part: str | Subkey | Terminal | list[str | Subkey | Terminal]


class StrfindObjconf(DynamicConf):
    rule: FindConfRule | list[FindConfRule]


class StrReplaceObjconf(DynamicConf):
    rule: StrReplaceConfRule | list[StrReplaceConfRule]


class StrTransformObjconf(DynamicConf):
    rule: StrTransformConfRule | list[StrTransformConfRule]


class SubelementObjconf(DynamicConf):
    path: str
    token_key: str


class SubstrObjconf(DynamicConf):
    start: int
    length: int


class SumObjconf(DynamicConf):
    sum_key: str
    group_key: str | None


class TimeoutObjconf(DynamicConf):
    days: int
    seconds: int
    microseconds: int
    milliseconds: int
    minutes: int
    hours: int
    weeks: int


class TokenizerObjconf(DynamicConf):
    delimiter: str
    dedupe: bool
    sort: bool
    token_key: str


class TruncateObjconf(DynamicConf):
    count: int
    start: int


class TypecastObjconf(DynamicConf):
    type: CastType


class UdfObjconf(DynamicConf):
    func: Callable[..., Any]


class UniqObjconf(DynamicConf):
    uniq_key: str
    limit: int


class UrlBuilderObjconf(DynamicConf):
    base: str
    ext: str
    path: str
    param: ParsedParam | list[ParsedParam]


class UrlParseObjconf(DynamicConf):
    parse_key: str


class XpathFetchPageObjconf(DynamicConf):
    url: str
    xpath: str
    html5: bool
