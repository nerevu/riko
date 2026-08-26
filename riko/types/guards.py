# vim: sw=4:ts=4:expandtab
"""
Provides type guard functions for riko types.
"""

from collections.abc import Mapping
from typing import Any, TypeGuard

from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeIs

from riko._objectify import Objectify
from riko._strutils import replacer
from riko.types.general import Item
from riko.types.modules import ConfArg
from riko.types.values import (
    MISSING,
    BasicList,
    BasicValue,
    BasicValueType,
    MissingType,
    Sentinal,
    SentinalValue,
    StatefulItem,
    StreamState,
)


def is_mapping[D, VT](val: Mapping[D, VT] | object) -> TypeIs[Mapping[D, VT]]:
    failure = False

    # Delay calling isinstance(val, Mapping) as much as possible
    if not (success := isinstance(val, (dict, CaseInsensitiveDict, Objectify))):
        failure = isinstance(val, (str, int, float))

    return success or (False if failure else isinstance(val, Mapping))


def is_stateful_item(val: Item | StatefulItem) -> TypeGuard[StatefulItem]:
    return isinstance(val.get("state"), StreamState) if is_mapping(val) else False


def is_missing_type(val: Item | MissingType | None) -> TypeIs[MissingType]:
    return val is MISSING


def is_known_sequence[VT](val: object) -> TypeIs[list[VT] | tuple[VT, ...]]:
    return isinstance(val, (list, tuple))


def is_mapping_seq(
    val: list[Any] | tuple[Any, ...],
) -> TypeGuard[list[Mapping[Any, object]] | tuple[Mapping[Any, object], ...]]:
    return bool(val and is_mapping(val[0]))


def is_value_seq(
    val: list[Any] | tuple[Any, ...],
) -> TypeGuard[BasicList | tuple[BasicValue, BasicValue]]:
    return bool(val and isinstance(val[0], BasicValueType))


def is_sentinal[VT](val: Mapping[str, VT], **kwargs: object) -> TypeGuard[Sentinal]:
    if SentinalValue in val:
        sentinal = str(val[SentinalValue])
        key = replacer(sentinal, "")
    else:
        key = None

    return all([key, (len(val) in {2, 3}), key in kwargs])


def is_type_value(val: Mapping[Any, Any]) -> TypeGuard[ConfArg]:
    return len(val) == 2 and "type" in val and "value" in val
