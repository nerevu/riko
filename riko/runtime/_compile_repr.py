# vim: sw=4:ts=4:expandtab
"""Provides the unquoted identifier placeholder rendered into generated source."""

from __future__ import annotations

from functools import total_ordering
from typing import TYPE_CHECKING

from riko.types._compiler import ModuleOptionValues
from riko.types._pipeline import StepValue
from riko.types.modules import AnyModuleRawConf

if TYPE_CHECKING:
    from riko.execution.context import Context


def cmp(a: object, b: object) -> int:
    return (a > b) - (a < b)  # type: ignore[operator]


@total_ordering
class Id:
    """An object that is not quoted as literal by repr."""

    def __init__(self, name: object) -> None:
        self.name = name

    def __repr__(self) -> str:
        return str(self.name)

    def __lt__(self, other: object) -> int:
        if isinstance(other, Id):
            return cmp(self.name, other.name)
        else:
            return -1

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Id):
            return self.name == other.name
        else:
            return False


type PyKwargValue = (
    AnyModuleRawConf | ModuleOptionValues | Context | list[StepValue | Id]
)
