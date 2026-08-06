# vim: sw=4:ts=4:expandtab
"""
riko._objectify
~~~~~~~~~~~~~~~
Attribute-access config wrappers: the ``Objectify`` mapping (over meza's
``Objectify``), the ``DynamicConf`` parsed-config base every module config
derives from, and the ``objectify`` factory.
"""

from collections.abc import Iterator, Mapping, Sequence
from time import struct_time
from typing import TYPE_CHECKING, Any, TypeVar, overload

from meza.fntools import Objectify as _Objectify
from requests.structures import CaseInsensitiveDict

from riko.types.general import ItemOrValue, SyncArgFunc

_VT = TypeVar("_VT")


if TYPE_CHECKING:

    class Objectify(Mapping[str, _VT]):
        """
        Creates an object with dynamically set attributes. Useful
        for accessing the kwargs of a function as attributes.
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
        Creates an object with dynamically set attributes. Useful
        for accessing the kwargs of a function as attributes.
        """

        def __init__(self, data, *args, **kwargs):
            """
            Objectify constructor

            Args:
                data (dict): The attributes to set
                defaults (dict): The default attributes

            Examples:
                >>> kw = Objectify({'KEY': 'foo'})
                >>> kw.key
                'foo'
                >>> kw['key']
                'foo'
                >>> kw.get('key')
                'foo'

            """
            _data = {k.lower(): v for k, v in data.items()}
            super().__init__(_data, *args, **kwargs)

        def __len__(self):
            return len(self.data)


class DynamicConf(Objectify[Any]):
    """
    A parsed configuration bag with case-insensitive attribute and mapping
    access. The base type every parsed module config is, and the fallback
    config type for modules without a precise config.
    """


@overload
def objectify[T](data: Mapping[str, T]) -> Objectify[T]: ...  # noqa: E704
@overload  # noqa: E302
def objectify[T](data: T) -> T: ...  # noqa: E704
@overload  # noqa: E302
def objectify[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    data: Mapping[str, T], func: SyncArgFunc
) -> Objectify[T]: ...
@overload  # noqa: E302
def objectify[T](  # noqa: E704
    data: Sequence[T], func: SyncArgFunc
) -> list[ItemOrValue | Objectify[object]]: ...
@overload  # noqa: E302
def objectify[T](  # noqa: E704
    data: T, func: SyncArgFunc
) -> T | ItemOrValue: ...
def objectify[T](  # noqa: E302
    data: T, func: SyncArgFunc | None = None, **defaults: object
) -> T | ItemOrValue | Objectify[T] | list[T] | list[ItemOrValue | Objectify[object]]:
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
