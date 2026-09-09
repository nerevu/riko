from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePath
from time import struct_time

type AnyStr = str | bytes
type BasicValue = str | int
type NumLike = float | int | Decimal
type Scalar = str | int | float | Decimal
type Temporal = datetime | date | struct_time
type DateLike = str | int | datetime | date | struct_time
type SortableValue = Scalar | Temporal
type PrimitiveValue = SortableValue | None
type Hashable = int | float | str | Decimal | date | struct_time | None
type DateDict = dict[str, str | int | date | bool]

# Instance Types
AnyStrType: tuple[type[str], type[bytes]] = (str, bytes)
BasicValueType: tuple[type[str], type[int]] = (str, int)
TemporalType: tuple[type, ...] = (datetime, date, struct_time)
DateLikeType: tuple[type, ...] = (str, int, datetime, date, struct_time)
NumLikeType: tuple[type, ...] = (float, int, Decimal)
PrimitiveValueType: tuple[type, ...] = (
    str,
    int,
    float,
    Decimal,
    datetime,
    date,
    struct_time,
)
HashableType: tuple[type, ...] = (str, int, float, Decimal, date, struct_time, PurePath)
