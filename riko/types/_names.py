from enum import StrEnum


class ModuleName(StrEnum):
    """A type-safe module name."""


class TargetName(StrEnum):
    """A type-safe target name."""


type ModuleNameLike = str | ModuleName
type TargetLike = str | TargetName
