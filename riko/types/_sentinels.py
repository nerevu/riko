from enum import Enum, auto
from typing import NotRequired, TypedDict


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
