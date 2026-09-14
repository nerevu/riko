# vim: sw=4:ts=4:expandtab
"""
riko.ext.names
~~~~~~~~~~~~~~

Provides module-name normalization and discovery categories.
"""

from typing import TYPE_CHECKING, overload

from riko.types._names import ModuleName, normalize_module_name

if TYPE_CHECKING:
    from riko.types.modules import ModuleCategory, ModuleMetadata

SINK_NAMES: frozenset[str] = frozenset({"output", "write"})


@overload
def derive_category(  # noqa: E704
    metadata: "ModuleMetadata", *, provider: str = "riko", override: str
) -> str: ...
@overload  # noqa: E302
def derive_category(  # noqa: E704
    metadata: "ModuleMetadata", *, provider: str = "riko", override: None = ...
) -> "ModuleCategory": ...
def derive_category(  # noqa: E302
    metadata: "ModuleMetadata", *, provider: str = "riko", override: str | None = None
) -> "ModuleCategory | str":
    """
    Derives the user-facing discovery category for a module.

    Categories are based on data-flow role, not the runtime module type.
    """
    if override is not None:
        result = override
    elif provider != "riko":
        result = provider
    elif metadata.name in SINK_NAMES:
        result = "sink"
    elif metadata.subtype == "source":
        result = "source"
    else:
        result = "transform"

    return result


__all__ = ["SINK_NAMES", "ModuleName", "derive_category", "normalize_module_name"]
