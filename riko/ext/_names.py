# vim: sw=4:ts=4:expandtab
"""
Provides module-name normalization and discovery categories.

Examples:

    Basic usage::

        >>> from riko import get_module_metadata
        >>> from riko.ext import derive_category
        >>>
        >>> metadata = get_module_metadata("fetch", strict=True)
        >>> derive_category(metadata)
        'source'

"""

from __future__ import annotations

from typing import TYPE_CHECKING, overload

from riko.base._config import SINK_NAMES

if TYPE_CHECKING:
    from riko.types.modules import ModuleCategory, ModuleMetadata


@overload
def derive_category(  # noqa: E704
    metadata: ModuleMetadata, *, provider: str = "riko", override: str
) -> str: ...
@overload  # noqa: E302
def derive_category(  # noqa: E704
    metadata: ModuleMetadata, *, provider: str = "riko", override: None = ...
) -> ModuleCategory: ...
def derive_category(  # noqa: E302
    metadata: ModuleMetadata, *, provider: str = "riko", override: str | None = None
) -> ModuleCategory | str:
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
