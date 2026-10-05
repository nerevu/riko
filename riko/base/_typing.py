# vim: sw=4:ts=4:expandtab
"""Runtime type-hint resolution helpers for PEP 563 annotations."""

from __future__ import annotations

from types import ModuleType
from typing import TYPE_CHECKING, Any, get_type_hints

if TYPE_CHECKING:
    from collections.abc import Mapping


def resolve_type_hints(
    obj: object,
    *namespaces: ModuleType | Mapping[str, object],
    include_extras: bool = False,
) -> dict[str, Any]:
    """
    Resolves an object's type hints, supplementing the lookup namespace.

    ``get_type_hints`` evaluates PEP 563 (``from __future__ import annotations``)
    string annotations against the defining module's globals, so a name imported
    only under ``TYPE_CHECKING`` fails to resolve. Each entry in ``namespaces``,
    a module or a mapping, is merged into the local namespace in order (later
    entries win) so those forward references resolve.

    Args:

        obj: The module, class, or callable whose hints to resolve.
        namespaces: Modules or mappings whose names supplement the local namespace.
        include_extras: Whether to keep ``Annotated`` metadata.

    Returns:

        The resolved ``name -> type`` mapping.

    Examples:

        >>> from collections.abc import Iterator
        >>> import collections.abc as abc
        >>>
        >>> def pipe(items) -> "Iterator[int]":
        ...     return iter(items)
        >>>
        >>> resolve_type_hints(pipe, abc)["return"]
        collections.abc.Iterator[int]

    """
    localns: dict[str, object] = {}

    for namespace in namespaces:
        localns.update(
            vars(namespace) if isinstance(namespace, ModuleType) else namespace
        )

    return get_type_hints(obj, localns=localns, include_extras=include_extras)
