# vim: sw=4:ts=4:expandtab
"""
Sort-key construction and grouping helpers used by built-in modules.

Attributes:

    SORT_FILLER: Orderable stand-in (``-inf``) for a sort value that cannot be cast.
    DATELIKE_TYPES: Cast types reduced to epoch timestamps for sorting.
    INVALID_TYPES: Cast types with no usable sort value or typed default.
    NON_SORTABLE: Types (mappings, sequences) that fall back to the default key.

"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, ItemsView, Iterable, Mapping, Sequence
from datetime import UTC, date, tzinfo
from datetime import datetime as dt
from decimal import Decimal
from math import isnan
from time import struct_time
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from riko.base._logging import get_logger
from riko.coercion._dates import date_to_datetime, resolve_aware_datetime
from riko.coercion.cast import CAST_SWITCH, cast_value, resolve_cast_type
from riko.types._enums import CastType
from riko.types._guards import is_mapping
from riko.types._scalars import PrimitiveValue, SortableValue

if TYPE_CHECKING:
    from logging import Logger

logger: Logger = get_logger(__name__)

SORT_FILLER = float("-inf")
DATELIKE_TYPES = frozenset({CastType.DATE, CastType.DATETIME})
INVALID_TYPES = frozenset({CastType.LOCATION, CastType.NONE})
NON_SORTABLE = (Mapping, Sequence)

B = TypeVar("B", Literal[True], Literal[False])


def _resolve_uncastable(
    value: Mapping | Sequence | PrimitiveValue, msg: str, default: SortableValue
) -> SortableValue | None:
    """
    Handles a value that cannot be cast for a sort key, degrading by type.

    A scalar (``str``/``int``/``struct_time``) is returned uncast since it is
    already orderable; a container is replaced with ``default``, which the caller
    supplies as an orderable filler. Every branch logs a warning rather than
    raising, so a heterogeneous stream still sorts.

    Args:

        value: The value that failed casting.
        msg: The warning prefix describing the failed cast.
        default: The orderable filler used for non-scalar values.

    Returns:

        The original value when it is already orderable, else ``default``.

    """
    if isinstance(value, (str, int, struct_time)):
        msg += ". Returning value without casting."
        logger.warning(msg)
        casted = value
    elif isinstance(value, NON_SORTABLE):
        msg += ". Returning default value."
        logger.warning(msg)
        casted = default
    else:
        msg += ". Returning value without casting."
        logger.warning(msg)
        casted = value

    return casted


def _warn_and_default(type_name: str, default: SortableValue) -> SortableValue:
    msg = f"Received non-sortable {type_name} value. Returning default instead."
    logger.warning(msg)
    return default


def _resolve_default(
    cast_type: CastType | None, default: PrimitiveValue | None
) -> SortableValue:
    """
    Resolves the sort-key default for a cast type, kept orderable.

    A cast default marks "no value" and may be non-orderable (``NaN`` for ``float``/
    ``decimal``, ``None`` for dates). Those and all date-like types collapse to
    ``SORT_FILLER`` (``-inf``), which compares against real keys. A falsy-but-valid
    caller default (``0``/``False``) is preserved. Only ``None`` and a mapping default
    fall back to the empty string, as does a cast type with no usable typed default.

    Args:

        cast_type: The cast type, or ``None`` for no casting.
        default: The caller-supplied default, if any.

    Returns:

        An orderable default suitable as a sort-key filler.

    """
    resolved = ""

    if default is None:
        if cast_type is not None and cast_type not in INVALID_TYPES:
            _default = CAST_SWITCH[cast_type].get("default")
            unorderable = isinstance(_default, (float, Decimal)) and isnan(_default)

            if unorderable or cast_type in DATELIKE_TYPES:
                resolved = SORT_FILLER
            elif _default is not None:
                resolved = cast("SortableValue", _default)
    elif isinstance(default, Mapping):
        logger.warning(f"Invalid {default=}. Setting to empty string.")
    else:
        resolved = default

    return resolved


def def_itemgetter(
    attr: str,
    default: PrimitiveValue | None = None,
    type_: str | None = None,
    fallback_tzinfo: tzinfo = UTC,
) -> Callable[[Mapping | PrimitiveValue], SortableValue]:
    """
    Like operator.itemgetter but fills in missing fields with a typed default.

    Args:

        attr: The field read from each item.
        default: The value used when the field is missing or uncastable.
        type_: Optional cast type applied to the value.
        fallback_tzinfo: Timezone assigned to naive datetimes before they are
            reduced to sortable timestamps.

    Returns:

        A key function mapping an item to a sortable value.

    Examples:

        >>> keyfunc = def_itemgetter("n", type_="int")
        >>> keyfunc({"n": 5})
        5
        >>> keyfunc({})
        0
        >>> # an invalid number sorts via -inf, not NaN
        >>> keyfunc = def_itemgetter("n", type_="float")
        >>> keyfunc({}), keyfunc({"n": "abc"})
        (-inf, -inf)

    """
    resolved = resolve_cast_type(type_)
    cast_type = None if resolved is CastType.PASS else resolved
    sort_default = _resolve_default(cast_type, default)
    invalid_type = cast_type in INVALID_TYPES

    def keyfunc(item: Mapping | PrimitiveValue) -> SortableValue:
        if is_mapping(item):
            value = item.get(attr)
        else:
            value = item

        msg = f"Invalid cast type={type_} for key '{attr}'"

        if invalid_type:
            casted = _resolve_uncastable(value, msg, sort_default)
        elif cast_type is not None:
            _casted = cast_value(value, cast_type)
            casted = cast("PrimitiveValue", _casted)
        elif isinstance(value, (str, int, struct_time)):
            casted = value
        elif isinstance(value, NON_SORTABLE):
            casted = _warn_and_default(type(value).__name__, sort_default)
        elif value is not None:
            casted = value
        else:
            casted = sort_default

        if cast_type in DATELIKE_TYPES and isinstance(casted, (date, dt)):
            if isinstance(casted, dt):
                aware = resolve_aware_datetime(casted, fallback_tzinfo=fallback_tzinfo)
            else:
                aware = date_to_datetime(casted, fallback_tzinfo=fallback_tzinfo)

            casted = aware.timestamp()

        if casted is None or (isinstance(casted, (float, Decimal)) and isnan(casted)):
            casted = sort_default

        return casted

    return keyfunc


def build_sort_key(
    attr: str,
    default: PrimitiveValue | None = None,
    type_: str | None = None,
    fallback_tzinfo: tzinfo = UTC,
) -> Callable[[Mapping | PrimitiveValue], tuple[bool, SortableValue]]:
    """
    Builds a sort key that tracks whether the sorted item contains the sort field.

    The key is a ``(present, value)`` pair, so an item without the field never
    has its filler compared against real values and sorts first ascending (last
    descending) whatever the cast type. A ``default`` stands in for the missing
    field instead, cast like any other value, so the item sorts among the rest.
    A present but uncastable value still degrades to the orderable filler
    ``def_itemgetter`` supplies.

    Args:

        attr: The field read from each item.
        default: The value an item lacking ``attr`` sorts by, if any.
        type_: Optional cast type applied to the value.
        fallback_tzinfo: Fallback timezone assigned to naive datetimes

    Returns:

        A key function mapping an item to a ``(present, value)`` pair.

    Examples:

        >>> keyfunc = build_sort_key("n", type_="int")
        >>> keyfunc({"n": "-5"}), keyfunc({}), keyfunc({"n": "abc"})
        ((True, -5), (False, 0), (True, 0))
        >>> sorted([{"n": 3}, {}, {"n": -5}], key=build_sort_key("n"))
        [{}, {'n': -5}, {'n': 3}]
        >>> sorted([{"n": 3}, {}, {"n": -5}], key=build_sort_key("n", 0))
        [{'n': -5}, {}, {'n': 3}]

    """
    keyfunc = def_itemgetter(attr, type_=type_, fallback_tzinfo=fallback_tzinfo)

    def key(item: Mapping | PrimitiveValue) -> tuple[bool, SortableValue]:
        value = item.get(attr) if isinstance(item, Mapping) else item

        if value is None and default is not None:
            keyed = (True, keyfunc(default))
        else:
            keyed = (value is not None, keyfunc(item))

        return keyed

    return key


def group_by[T: Mapping | PrimitiveValue](
    content: Iterable[T], attr: str, default: PrimitiveValue | None = None
) -> ItemsView[str, list[T]]:
    """
    Groups items by the stringified value of a field.

    Args:

        content: The items to group.
        attr: The field read from each item.
        default: The value used when an item lacks ``attr``.

    Returns:

        A view of ``(group value, items)`` pairs, one per distinct value.

    Examples:

        >>> items = [{"k": "a"}, {"k": "b"}, {"k": "a"}]
        >>> sorted((k, len(v)) for k, v in group_by(items, "k"))
        [('a', 2), ('b', 1)]

    """
    keyfunc = def_itemgetter(attr, default)
    groups = defaultdict(list)

    for item in content:
        key = str(keyfunc(item))
        groups[key].append(item)

    return groups.items()
