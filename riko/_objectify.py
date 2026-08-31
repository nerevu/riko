# vim: sw=4:ts=4:expandtab
"""
riko._objectify
~~~~~~~~~~~~~~~
A corrected ``Objectify`` (over meza's ``Objectify``) plus an ``objectify`` factory.
It fixes:

* casing: meza keys on the raw attribute names, so ``kw.KEY`` and ``kw.key``
  diverge; here every key is lowercased at construction, so mixed-case input is
  always reached through its lowercase name.
* the ``Mapping`` contract: meza's class is a bare object with no ``__len__``;
  here it subclasses ``Mapping`` and adds ``__len__``, so ``len()`` and the
  mapping ABC work.

"""

from collections.abc import Iterator, Mapping, Sequence
from time import struct_time
from typing import TYPE_CHECKING, Any, TypeVar, overload

from meza.fntools import Objectify as _Objectify
from requests.structures import CaseInsensitiveDict

from riko.types._streams import ItemOrValue
from riko.types._wrappers import ArgCaster

_VT = TypeVar("_VT")


if TYPE_CHECKING:

    class Objectify(Mapping[str, _VT]):
        """
        A case-normalized mapping with attribute access to its items.

        Input keys are lowercased at construction, so a function's kwargs can be
        read as attributes (``kw.key``) regardless of their original casing.
        """

        def __init__(  # noqa: E704
            self, data: Mapping[str, _VT], *args: Any, **kwargs: object
        ) -> None: ...  # noqa: E704
        def __len__(self) -> int: ...  # noqa: E704
        def __getattribute__(self, *_: object) -> _VT: ...  # noqa: E704
        def __getitem__(self, *_: object) -> _VT: ...  # noqa: E704
        def __iter__(self) -> Iterator[str]: ...  # noqa: E704
        def iteritems(self) -> Iterator[tuple[str, _VT]]: ...  # noqa: E704
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


@overload
def objectify[T](data: Mapping[str, T]) -> Objectify[T]: ...  # noqa: E704
@overload  # noqa: E302
def objectify[T](data: T) -> T: ...  # noqa: E704
@overload  # noqa: E302
def objectify[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    data: Mapping[str, T], func: ArgCaster
) -> Objectify[T]: ...
@overload  # noqa: E302
def objectify[T](  # noqa: E704
    data: Sequence[T], func: ArgCaster
) -> list[ItemOrValue | Objectify[object]]: ...
@overload  # noqa: E302
def objectify[T](  # noqa: E704
    data: T, func: ArgCaster
) -> T | ItemOrValue: ...
def objectify[T](  # noqa: E302
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
    if isinstance(data, (dict, CaseInsensitiveDict, Mapping)):
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
