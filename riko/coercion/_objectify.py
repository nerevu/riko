# vim: sw=4:ts=4:expandtab
"""Provides case-insensitive mappings with dot-attribute access."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import struct_time
from typing import TYPE_CHECKING, overload

from riko.base._guards import is_mapping
from riko.base._iterutils import map_keys

if TYPE_CHECKING:
    from collections.abc import Callable, ItemsView, Iterator, KeysView, ValuesView
    from typing import Protocol

    from riko.types._streams import ItemOrValue
    from riko.types._wrappers import ArgCaster

    class _Valued[V](Protocol):
        @property
        def data(self) -> Mapping[str, V]: ...

    class _Objectify:
        def __init__(
            self,
            kwargs: Mapping[str, object],
            func: Callable[[object], object] | None = None,
            **defaults: object,
        ) -> None: ...
        def keys(self) -> KeysView[str]: ...
        def values[V](self: _Valued[V]) -> ValuesView[V]: ...
        def items[V](self: _Valued[V]) -> ItemsView[str, V]: ...
        def get[V](
            self: _Valued[V], key: str, default: V | None = None, /
        ) -> V | None: ...
        def __getitem__[V](self: _Valued[V], key: str) -> V: ...
        def __setitem__(self, key: str, value: object) -> None: ...
        def __getattr__[V](self: _Valued[V], name: str) -> V: ...
        def __delitem__(self, key: str) -> None: ...
        def __iter__(self) -> Iterator[str]: ...
        def iteritems[V](self: _Valued[V]) -> Iterator[tuple[str, V]]: ...

else:
    from meza.fntools import Objectify as _Objectify


class Objectify[V](_Objectify, Mapping[str, V]):
    """
    A case-normalized mapping with attribute access to its items.

    Input keys are lowercased at construction, so a function's kwargs can be
    read as attributes (``kw.key``) regardless of their original casing.
    """

    data: dict[str, V]

    def __init__(
        self,
        data: Mapping[str, V],
        func: Callable[[object], object] | None = None,
        **defaults: object,
    ) -> None:
        """
        Initializes the object with lowercased attribute names.

        Args:

            data: The attributes to set.
            func: Optional callable applied to each value on access.
            defaults: Default attributes, used for keys absent from ``data``.

        Examples:
            >>> kw = Objectify({"KEY": "foo"})
            >>> kw.key
            'foo'
            >>> kw["key"]
            'foo'
            >>> kw.get("key")
            'foo'

        """
        _data = map_keys(str.lower, data)
        super().__init__(_data, func, **defaults)

    def __len__(self) -> int:
        return len(self.data)

    def __contains__(self, key: object) -> bool:
        """
        Reports whether ``key`` is one of the stored keys.

        Membership matches the lowercased keys that ``keys()`` lists, so a
        missing key is absent even though reading it returns ``None``.

        Examples:
            >>> kw = Objectify({"URL": "x"})
            >>> ("url" in kw, "zzz" in kw)
            (True, False)

        """
        return key in self.data


@overload
def objectify[T](data: Mapping[str, T]) -> Objectify[T]: ...
@overload
def objectify[T](data: T) -> T: ...
@overload
def objectify[T](data: Mapping[str, T], func: ArgCaster) -> Objectify[T]: ...
@overload
def objectify[T](
    data: Sequence[T], func: ArgCaster
) -> list[ItemOrValue | Objectify[object]]: ...
@overload
def objectify[T](data: T, func: ArgCaster) -> T | ItemOrValue: ...
def objectify[T](
    data: T, func: ArgCaster | None = None, **defaults: object
) -> T | ItemOrValue | Objectify[T] | list[T] | list[ItemOrValue | Objectify[object]]:
    """
    Wraps a mapping as ``Objectify`` and applies ``func`` to any other value.

    Args:

        data: The value to objectify.
        func: Optional callable applied to non-mapping values.
        defaults: Default attributes for the resulting ``Objectify``.

    Returns:

        An ``Objectify`` for a mapping, a list for a sequence, ``func(data)``
        for any other value, or ``data`` unchanged when no ``func`` is given.

    """
    if is_mapping(data):
        objectified = Objectify(data, func=func, **defaults)
    elif func:
        if isinstance(data, (str, struct_time)):
            objectified = func(data)
        elif isinstance(data, Sequence):
            objectified = [objectify(d, func) for d in data]
        else:
            objectified = func(data)
    else:
        objectified = data

    return objectified
