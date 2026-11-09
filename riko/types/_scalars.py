"""Scalar, temporal, and primitive value typing aliases."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath
from time import struct_time
from uuid import UUID

from typing_extensions import TypeIs

from riko.base._typing import HashableType

type AnyStr = str | bytes
type BasicValue = int | str
type NumLike = int | float | Decimal
type Scalar = NumLike | str
type Temporal = date | datetime | struct_time
type DateLike = BasicValue | Temporal
type SortableValue = Scalar | Temporal
type PrimitiveValue = SortableValue | None
type NonNullHashable = (
    bool | Scalar | bytes | Temporal | PurePath | UUID | tuple[Hashable, ...]
)
type Hashable = NonNullHashable | None
type DateDict = dict[str, bool | int | str | date]


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
