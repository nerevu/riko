# vim: sw=4:ts=4:expandtab
"""
Resolved resources that an execution hands a module.

A module receives them as its ``resources`` argument, keyed by local binding name.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from riko.definitions._resource_types import Values
    from riko.types._io import Closeable


class ResourceView(Mapping[str, object]):
    """
    An execution-bound mapping of resolved resources by local binding name.

    Attribute access is a convenience for names that do not conflict with the mapping
    interface attributes/methods::

        resources.db

    Item access is authoritative and supports every resource name (including those
    that conflict with the mapping interface)::

        resources["items"]

    Args:

        values: Resolved resource values keyed by their local binding names.

    Examples:

        >>> from riko.execution._resource_view import ResourceView
        >>>
        >>> view = ResourceView({"db": object()})
        >>> view.db is view["db"]
        True
        >>> "db" in view
        True
        >>> value = object()
        >>> reserved = ResourceView({"keys": value})
        >>> reserved["keys"] is value
        True
        >>> reserved.keys is value
        False

    """

    __slots__ = ("_values",)

    def __init__(self, values: Values) -> None:
        self._values = dict(values)

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, name: str) -> object | Closeable:
        # copy/pickle probe attributes before ``_values`` is set
        if name == "_values" or name not in self._values:
            raise AttributeError(name)

        return self._values[name]

    def __getitem__(self, name: str) -> object | Closeable:
        return self._values[name]

    def __contains__(self, name: object) -> bool:
        return name in self._values


__all__ = ["ResourceView"]
