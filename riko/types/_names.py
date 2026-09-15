from enum import StrEnum


class ModuleName(StrEnum):
    """A type-safe module name."""


type ModuleNameLike = str | ModuleName
