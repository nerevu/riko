from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

if TYPE_CHECKING:
    from riko.cast import BasicCastType

    from ._collections import BasicArg, RikoDict, RikoList
    from ._dynamic_conf import DynamicConf
    from ._names import TargetLike
    from ._scalars import PrimitiveValue
    from ._streams import Item
    from .modules import AnyConfRule, CountValues, Skip


class Defaults(TypedDict, total=False):
    col_names: list[str] | None
    combine: Literal["and", "or"]
    count: int
    count_key: str | None
    clean: bool
    currency: str  # TODO this should be an enum/literal
    dedupe: bool
    default: BasicArg
    delimiter: str
    detag: bool
    encoding: str
    input_key: str
    format: str
    group_key: str | None
    has_header: bool
    html5: bool
    join_key: str | None
    length: int
    limit: int
    lower: bool
    max_wait: int
    max_len: int
    memoize: bool
    mode: str
    multi: bool
    name: str
    prompt: str
    param: dict[str, str | None]
    parse_key: str
    permit: bool
    precision: int
    pubDate: str
    quotechar: str
    rule: AnyConfRule
    sanitize: bool
    separator: str
    skip_rows: int
    sort: bool
    splits: int
    start: int
    stop: bool
    strict: bool
    sum_key: str
    target: TargetLike | None
    test: bool
    token_key: str
    type: str
    uniq_key: str
    url: str
    wait: int


class Opts(TypedDict, total=False):
    ftype: BasicCastType
    ptype: BasicCastType
    assign: str
    count: CountValues
    emit: bool
    extract: str
    field: str
    listize: bool
    objectify: bool
    parse: bool
    pollable: bool
    skip_if: SkipIf


class Casted[T, E](NamedTuple):
    field: T
    extraction: E
    conf: DynamicConf


class ItemDispatch[T, E](NamedTuple):
    item: Item | RikoDict
    casted: Casted[T, E]


class ValueDispatch[T, E](NamedTuple):
    item: PrimitiveValue | RikoList
    casted: Casted[T, E]


type ItemOrValueDispatch[T, E] = ItemDispatch[T, E] | ValueDispatch[T, E]

type SkipFunc = Callable[[Item], bool]
type SkipIf = SkipFunc | Skip | Iterable[SkipFunc] | Iterable[Skip]
