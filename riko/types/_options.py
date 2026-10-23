"""Module defaults, decoration options, call options, and dispatch typing contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

import attrs
from attrs import define

from riko.base._recordutils import serialize_attrs
from riko.base._require_guards import (
    require_from_form,
    require_from_typed_dict,
    require_instance,
    validator_from_require,
)

from ._pipedef import CountValues

if TYPE_CHECKING:
    from riko.base._require_guards import TypeRequire
    from riko.coercion._dynamic_conf import DynamicConf

    from ._enums import BasicCastType, ExecutionMode, FmtLike
    from ._scalars import PrimitiveValue
    from ._streams import Item
    from ._values import BasicArg, Inputs, RikoList
    from ._wrappers import ParserOutput
    from .modules import AnyConfRule, OptionValues, Skip


class Defaults(TypedDict, total=False):
    col_names: list[str] | None
    combine: Literal["and", "or"]
    count: int
    count_key: str | None
    clean: bool
    currency: str
    dedupe: bool
    default: BasicArg
    delimiter: str
    detag: bool
    encoding: str
    input_key: str
    format: str
    fmt: FmtLike | None
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
    normalize_key: str
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
    test: bool
    token_key: str
    type: str
    uniq_key: str
    url: str
    wait: int


class DecorationOptions(TypedDict, total=False):
    ftype: BasicCastType
    ptype: BasicCastType
    assign: str
    count: CountValues
    emit: bool | Callable[[ParserOutput], bool] | None
    extract: str
    field: str
    listize: bool
    objectify: bool
    parse: bool
    pollable: bool
    skip_if: SkipIf


class SharedDecorationOptions(TypedDict, total=False):
    """Decoration options every pipe decorator reads."""

    defaults: Defaults | None
    isasync: bool
    ftype: BasicCastType
    ptype: BasicCastType
    assign: str
    extract: str
    field: str
    listize: bool
    objectify: bool
    parse: bool


class OperatorDecorationOptions(SharedDecorationOptions, total=False):
    """Decoration options the ``operator`` decorator reads."""

    pollable: bool
    emit: bool | Callable[[ParserOutput], bool] | None


class ProcessorDecorationOptions(OperatorDecorationOptions, total=False):
    """Decoration options the ``processor`` decorator reads."""

    skip_if: SkipIf


class Casted[T, E](NamedTuple):
    field: T
    extraction: E
    conf: DynamicConf


class ItemDispatch[T, E](NamedTuple):
    item: Item
    casted: Casted[T, E]


class ValueDispatch[T, E](NamedTuple):
    item: PrimitiveValue | RikoList
    casted: Casted[T, E]


type ItemOrValueDispatch[T, E] = ItemDispatch[T, E] | ValueDispatch[T, E]

type SkipFunc = Callable[[Item], bool]
type SkipIf = SkipFunc | Skip | Iterable[SkipFunc] | Iterable[Skip]


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
