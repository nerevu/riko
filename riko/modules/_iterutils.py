# vim: sw=4:ts=4:expandtab
"""
Sort-key construction and grouping helpers used by built-in pipeline modules.

Attributes:

    SORT_FILLER: Orderable stand-in (``-inf``) for a missing sort key.
    DATELIKE_TYPES: Cast types reduced to epoch timestamps for sorting.
    INVALID_DEF_TYPES: Cast types with no usable typed default.
    INVALID_TYPES: Cast types that cannot be cast at all.
    NON_SORTABLE: Types (mappings, sequences) that fall back to the default key.

"""

from collections import defaultdict
from collections.abc import Callable, ItemsView, Iterable, Mapping, Sequence
from datetime import UTC, date, tzinfo
from datetime import datetime as dt
from decimal import Decimal
from logging import Logger
from math import isnan
from time import struct_time
from typing import Literal, TypeVar, cast

import pygogo as gogo
from requests.structures import CaseInsensitiveDict

from riko.coercion._dates import date_to_datetime, ensure_tzinfo
from riko.coercion.cast import CAST_SWITCH, cast_value
from riko.types._enums import CastType
from riko.types._scalars import PrimitiveValue, SortableValue

logger: Logger = gogo.Gogo(__name__, monolog=True).logger

SORT_FILLER = float("-inf")
DATELIKE_TYPES = frozenset({CastType.DATE, CastType.DATETIME})
INVALID_DEF_TYPES = frozenset({CastType.LOCATION, CastType.NONE})
INVALID_TYPES = frozenset({CastType.LOCATION, CastType.PASS, CastType.NONE})
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
    raising, so a heterogeneous feed still sorts.

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
    elif isinstance(value, (dict, CaseInsensitiveDict, list, tuple, Mapping, Sequence)):
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
    type_: str | None, invalid_type: bool | None, default: PrimitiveValue | None
) -> SortableValue:
    """
    Resolves the sort-key default for a cast type, kept orderable.

    A cast default marks "no value" and may be non-orderable (``NaN`` for
    ``float``/``decimal``, ``None`` for dates). Those and all date-like types
    collapse to ``SORT_FILLER`` (``-inf``), which compares against real keys. A
    falsy-but-valid caller default (``0``/``False``) is preserved; only ``None``
    and a mapping default fall back to the empty string.

    Args:

        type_: The cast type name, or ``None`` for no casting.
        invalid_type: Whether ``type_`` has no usable typed default.
        default: The caller-supplied default, if any.

    Returns:

        An orderable default suitable as a sort-key filler.

    """
    resolved = ""

    if invalid_type and default is None:
        logger.warning(f"Invalid cast type={type_}. Setting default to empty string.")
    elif type_ and default is None:
        _default = CAST_SWITCH[type_].get("default")
        unorderable = isinstance(_default, (float, Decimal)) and isnan(_default)

        if unorderable or type_ in DATELIKE_TYPES:
            resolved = SORT_FILLER
        elif _default is not None:
            resolved = cast(SortableValue, _default)
    elif isinstance(default, Mapping):
        logger.warning(f"Invalid {default=}. Setting to empty string.")
    elif default is not None:
        resolved = default

    return resolved


def def_itemgetter(
    attr: str,
    default: PrimitiveValue | None = None,
    type_: str | None = None,
    fallback_tzinfo: tzinfo = UTC,
) -> Callable[[Mapping | PrimitiveValue], SortableValue]:
    """
    Like operator.itemgetter but fills in missing keys with a typed default.

    Args:

        attr: The key read from each item.
        default: The value used when the key is missing or uncastable.
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
    not_switch = type_ and type_ not in CAST_SWITCH
    invalid_def_type = bool((type_ in INVALID_DEF_TYPES) or not_switch)
    default = _resolve_default(type_, invalid_def_type, default)
    invalid_type = bool((type_ in INVALID_TYPES) or not_switch)

    def keyfunc(item: Mapping | PrimitiveValue) -> SortableValue:
        if isinstance(item, (dict, CaseInsensitiveDict, Mapping)):
            value = item.get(attr)
        else:
            value = item

        msg = f"Invalid cast type={type_} for key '{attr}'."

        if invalid_type:
            casted = _resolve_uncastable(value, msg, default)
        elif type_:
            _casted = cast_value(value, CastType(type_))
            casted = cast(PrimitiveValue, _casted)
        elif isinstance(value, (str, int, struct_time)):
            casted = value
        elif isinstance(value, NON_SORTABLE):
            casted = _warn_and_default(type(value).__name__, default)
        elif value is not None:
            casted = value
        else:
            casted = default

        if type_ in DATELIKE_TYPES and isinstance(casted, (date, dt)):
            if isinstance(casted, dt):
                aware = ensure_tzinfo(casted, fallback_tzinfo=fallback_tzinfo)
            else:
                aware = date_to_datetime(casted, fallback_tzinfo=fallback_tzinfo)

            casted = aware.timestamp()

        if casted is None or (isinstance(casted, (float, Decimal)) and isnan(casted)):
            casted = default

        return casted

    return keyfunc


# TODO: move this to meza.process.group
def group_by[T: Mapping | PrimitiveValue](
    content: Iterable[T], attr: str, default: PrimitiveValue | None = None
) -> ItemsView[str, list[T]]:
    """
    Groups items by the stringified value of a key.

    Args:

        content: The items to group.
        attr: The key read from each item.
        default: The value used when an item lacks ``attr``.

    Returns:

        A view of ``(key, items)`` pairs, one per distinct key.

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
