"""Missing-value, stream-state, and terminal sentinel types."""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, NotRequired, TypedDict, TypeGuard

from typing_extensions import TypeIs

from ._strutils import replacer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._streams import Item


class MissingType:
    def __repr__(self) -> str:
        return "<MISSING>"


MISSING = MissingType()


class StreamState(Enum):
    PENDING = auto()
    DONE = auto()


class Sentinel(TypedDict):
    terminal: str
    type: str
    path: NotRequired[str]


SentinelValue: str = "terminal"


def is_missing_type(val: Item | MissingType | None) -> TypeIs[MissingType]:
    return val is MISSING


def is_sentinel[VT](val: Mapping[str, VT], **kwargs: object) -> TypeGuard[Sentinel]:
    if SentinelValue in val:
        sentinel = str(val[SentinelValue])
        key = replacer(sentinel, "")
    else:
        key = None

    return all([key, (len(val) in {2, 3}), key in kwargs])
