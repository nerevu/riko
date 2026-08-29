from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from riko.dotdict import DotDict

    from ._scalars import BasicValue, PrimitiveValue


type Inputs = Mapping[str, str | int | bool]
type Key = str | dict[str, str]

# Args
type BasicMapping = Mapping[str, BasicValue]
type BasicArg = BasicValue | BasicMapping | Sequence[BasicValue]

# Returns
type BasicDict = (
    dict[str, str]
    | dict[str, bool]
    | dict[str, int]
    | dict[str, Decimal]
    | dict[str, float]
)
type BasicList = list[str] | list[bool] | list[int] | list[Decimal] | list[float]
type BasicReturn = BasicValue | BasicDict | BasicList | tuple[BasicValue, ...]

type Stringy = str | "StringyList" | "StringyDict"
type StringyDict = dict[str, Stringy]
type StringyList = list[Stringy]

type RikoDict = (
    BasicDict
    | StringyDict
    | dict[str, PrimitiveValue]
    | dict[str, BasicDict]
    | dict[str, BasicList]
    | "DotDict[PrimitiveValue]"
)
type RikoList = BasicList | list[BasicDict] | StringyList
type RikoValue = PrimitiveValue | RikoDict | RikoList
