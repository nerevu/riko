# vim: sw=4:ts=4:expandtab
"""
Provides function pretty printing
"""

from collections.abc import Mapping
from functools import total_ordering
from typing import cast

from riko.context import Context
from riko.types.modules import (
    AnyModuleRawConf,
    ConfArg,
    RawConfValues,
    Value,
)


def cmp(a: object, b: object) -> int:
    return (a > b) - (a < b)  # type: ignore[operator]


@total_ordering
class Id:
    """An object that is not quoted as literal by repr"""

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


def repr_arg(
    arg: str
    | RawConfValues
    | AnyModuleRawConf
    | ConfArg
    | Id
    | Context
    # | EmbeddedModule
    | Value
    | dict[str, str]
    | None,
) -> str:
    """
    Formats a function argument prettily but as working code

    unicode encodable as ascii is formatted as str
    """
    if arg is None:
        value = ""
    elif isinstance(arg, str):
        value = repr(arg)
    elif isinstance(arg, (dict, Mapping)):
        joined = ", ".join(
            f"{repr_arg(k)}: {repr_arg(cast(RawConfValues, v))}" for k, v in arg.items()
        )
        value = f"{{{joined}}}"
    else:
        value = str(arg)

    return value


def repr_args(*args: dict[str, str]) -> str:
    """
    Formats a list of function arguments prettily but as working code
    """
    return f"[{', '.join(map(repr_arg, args))}]"
