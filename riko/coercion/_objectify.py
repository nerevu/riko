# vim: sw=4:ts=4:expandtab
"""Provides case-insensitive mappings with dot-attribute access."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from time import struct_time
from typing import TYPE_CHECKING, Any, TypeVar, overload

from meza.fntools import Objectify as _Objectify

from riko.base._guards import is_mapping

_VT = TypeVar("_VT")


if TYPE_CHECKING:
    from riko.types._streams import ItemOrValue
    from riko.types._wrappers import ArgCaster

    class Objectify(Mapping[str, _VT]):
        """
        A case-normalized mapping with attribute access to its items.

        Input keys are lowercased at construction, so a function's kwargs can be
        read as attributes (``kw.key``) regardless of their original casing.
        """

        def __init__(
            self, data: Mapping[str, _VT], *args: Any, **kwargs: object
        ) -> None: ...
        def __len__(self) -> int: ...
        def __getattribute__(self, *_: object) -> _VT: ...
        def __getitem__(self, *_: object) -> _VT: ...
        def __iter__(self) -> Iterator[str]: ...
        def iteritems(self) -> Iterator[tuple[str, _VT]]: ...
else:

    class Objectify(_Objectify, Mapping[str, _VT]):
        """
        A case-normalized mapping with attribute access to its items.

        Input keys are lowercased at construction, so a function's kwargs can be
        read as attributes (``kw.key``) regardless of their original casing.
        """

        def __init__(self, data, *args, **kwargs):
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
            _data = {k.lower(): v for k, v in data.items()}
            super().__init__(_data, *args, **kwargs)

        def __len__(self):
            return len(self.data)

        def __contains__(self, key):
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
