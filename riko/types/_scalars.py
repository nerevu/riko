"""Scalar, temporal, and primitive value typing aliases."""

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath
from time import struct_time
from typing import TypedDict
from uuid import UUID

from typing_extensions import TypeIs

from riko.base._guards import is_mapping
from riko.base._require_guards import typed_dict_keys
from riko.base._typing import HashableType

type AnyStr = str | bytes
type BasicValue = int | str
type NumLike = int | float | Decimal
type Scalar = NumLike | str
type Temporal = date | datetime | struct_time
type DateLike = BasicValue | Temporal | DateDict
type SortableValue = Scalar | Temporal
type PrimitiveValue = SortableValue | None

type NonNullHashable = (
    bool | Scalar | bytes | Temporal | PurePath | UUID | tuple[Hashable, ...]
)

type Hashable = NonNullHashable | None

_ZONE_LABEL = re.compile(r"UTC|UTC[+-]\d{2}:\d{2}(?::\d{2})?|[^/\s]+(?:/[^/\s]+)+")


class DateDict(TypedDict):
    """
    Describes a date and time as JSON-friendly fields.

    ``utime`` (epoch seconds) and ``utc_offset`` (seconds east of UTC) fix the moment
    and its offset. Converting the dict back to a ``datetime`` reads only these two,
    so the other fields cannot change the moment. ``year`` through ``daylight_savings``
    are the clock reading at that offset. They exist so a module can read a single part
    (e.g., ``date.year``) without formatting the date first. ``timezone`` names the zone
    (e.g., ``"America/Chicago"``), or the offset (``"UTC+08:00"``) when the zone has no
    name. ``day_of_week`` counts from Sunday as ``0``.
    """

    utime: int
    utc_offset: int
    timezone: str
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    day_of_week: int
    day_of_year: int
    daylight_savings: bool | None


def is_non_null_hashable(value: object) -> TypeIs[NonNullHashable]:
    """
    Reports whether a value is a non-null hashable scalar or a tuple of them.

    A tuple qualifies only when each element is ``None`` or itself qualifies, so a tuple
    holding a list does not.

    Args:

        value: The value to classify.

    Returns:

        ``True`` when ``value`` is a ``NonNullHashable``.

    Examples:

        >>> is_non_null_hashable(("v", 1, None))
        True
        >>> is_non_null_hashable(([1],))
        False
        >>> is_non_null_hashable(None), is_non_null_hashable(object())
        (False, False)

    """
    if isinstance(value, tuple):
        result = all(item is None or is_non_null_hashable(item) for item in value)
    else:
        result = isinstance(value, HashableType)

    return result


def is_datedict(value: object) -> TypeIs[DateDict]:
    """
    Reports whether a value is a ``datebuilder`` date dict.

    ``value`` must carry exactly the ``DateDict`` keys with integer ``utime`` and
    ``utc_offset``; and a ``timezone`` that is either ``"UTC"``, an offset such as
    ``"UTC+08:00"`` (``"UTC+06:55:25"`` when the offset has seconds), or a zone name
    such as ``"America/Chicago"``. A mapping that happens to hold a ``utime`` key does
    not qualify. Neither does an abbreviated ``timezone`` such as ``"CST"``.

    Args:

        value: The value to classify.

    Returns:

        ``True`` when ``value`` is a ``DateDict``.

    Examples:

        >>> is_datedict({"utime": 0})
        False
        >>> moment = dict.fromkeys(typed_dict_keys(DateDict)[0], 0)
        >>> is_datedict(moment | {"timezone": "America/Chicago"})
        True
        >>> is_datedict(moment | {"timezone": "CST"})
        False

    """
    return (
        is_mapping(value)
        and value.keys() == typed_dict_keys(DateDict)[0]
        and all(
            isinstance(value[key], int) and not isinstance(value[key], bool)
            for key in ("utime", "utc_offset")
        )
        and isinstance(zone := value["timezone"], str)
        and _ZONE_LABEL.fullmatch(zone) is not None
    )
