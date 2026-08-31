# vim: sw=4:ts=4:expandtab
"""
riko.ext.names
~~~~~~~~~~~~~~

Provides module-name normalization and discovery categories.
"""

from typing import TYPE_CHECKING, overload

from riko.types._names import ModuleName

if TYPE_CHECKING:
    from riko.types._names import ModuleNameLike
    from riko.types.modules import ModuleCategory, ModuleMetadata

SINK_NAMES: frozenset[str] = frozenset({"output", "write"})


def normalize_module_name(name: "ModuleNameLike | None") -> str:
    """Returns the canonical string module name."""
    return name.value if isinstance(name, ModuleName) else name or ""


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
    Returns the user-facing discovery category for a module.

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
