# vim: sw=4:ts=4:expandtab
"""
riko
~~~~
Provides functions for analyzing and processing streams of structured data

Examples:
    basic usage::

        >>> from riko.modules.itembuilder import pipe as itembuilder
        >>> from riko.modules.strreplace import pipe as strreplace
        >>> from riko.collections import SyncPipe
        >>>
        >>> ib_conf = {
        ...     'attrs': [
        ...         {'key': 'link', 'value': 'www.google.com'},
        ...         {'key': 'title', 'value': 'google'},
        ...         {'key': 'author', 'value': 'Tommy'}
        ...      ]
        ... }
        >>>
        >>> items = itembuilder(conf=ib_conf)
        >>> next(items)
        {'link': 'www.google.com', 'title': 'google', 'author': 'Tommy'}
        >>> sr_conf = {
        ...     'rule': [{'find': 'Tom', 'param': 'first', 'replace': 'Tim'}]
        ... }
        >>>
        >>> items = itembuilder(conf=ib_conf)
        >>> replaced = strreplace(next(items), conf=sr_conf, field='author')
        >>> next(replaced)['strreplace']
        'Timmy'

"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from importlib.metadata import PackageMetadata, metadata, version
from os import path as p
from time import struct_time
from typing import TYPE_CHECKING, Any, TypeVar, overload
from warnings import warn

from meza.fntools import Objectify as _Objectify
from requests.structures import CaseInsensitiveDict

from riko.context import Context, ExecutionMode  # noqa: F401
from riko.types.general import ItemOrValue, SyncArgFunc
from riko.types.values import PrimitiveValueType

# https://github.com/astral-sh/uv/issues/7533#issuecomment-2472804995
meta: PackageMetadata = metadata("riko")

PACKAGE_INFO = {
    "__version__": version("riko"),
    "__title__": meta["Name"],
    "__package_name__": meta["Name"],
    "__description__": meta.get("Summary") or meta.get("Description", ""),
    "__license__": meta.get("License-Expression") or meta.get("License", ""),
    "__author__": meta.get("Author", ""),
    "__email__": meta.get("Author-email", ""),
}


def __getattr__(name: str) -> str:
    if name in PACKAGE_INFO:
        return PACKAGE_INFO[name]
    else:
        msg = f"module {__name__} has no attribute {name}"
        raise AttributeError(msg)


__copyright__ = "Copyright 2015 Reuben Cummings"

PARENT_DIR = p.abspath(p.dirname(__file__))
ENCODING = "utf-8"
VT = TypeVar("VT")


def get_path(name: str) -> str:
    if name.startswith(("http", "file:")):
        url = name
    else:
        url = f"file://{p.join(PARENT_DIR, 'data', name)}"

    return url


def get_abspath(url: str, offline: bool = False) -> str:
    if url.startswith(("http", "file:///")):
        pass
    elif url.startswith("file://"):
        parent = p.dirname(p.dirname(__file__))
        rel_path = url[7:]
        abspath = p.abspath(p.join(parent, rel_path))
        url = f"file://{abspath}"
    elif offline:
        url = get_path(url)
    else:
        url = f"http://{url}" if url and "://" not in url else url

    return url


def replacer(content: str, old: str, new: str = "_") -> str:
    """
    Examples:
        >>> replacer('', '')
        ''
        >>> replacer('1abc', '')
        '_1abc'
        >>> replacer('a.b', '.')
        'a_b'

    """
    if old:
        replaced = content.replace(old, new)
    elif content and (content[0].isdecimal() or not content[0].isascii()):
        replaced = f"{new}{content}"
    else:
        replaced = content

    return replaced


if TYPE_CHECKING:

    class Objectify(Mapping[str, VT]):
        """
        Creates an object with dynamically set attributes. Useful
        for accessing the kwargs of a function as attributes.
        """

        def __init__(  # noqa: E704
            self, data: Mapping[str, VT], *args: Any, **kwargs: object
        ) -> None: ...  # noqa: E704
        def __len__(self) -> int: ...  # noqa: E704
        def __getattribute__(self, *_: object) -> VT: ...  # noqa: E704
        def __getitem__(self, *_: object) -> VT: ...  # noqa: E704
        def __iter__(self) -> Iterator[str]: ...  # noqa: E704
        def iteritems(self) -> Iterator[tuple[str, VT]]: ...  # noqa: E704
else:

    class Objectify(_Objectify, Mapping[str, VT]):
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


def Objconf[VT](  # noqa: N802
    values: Mapping[str, VT], *args: Any, **kwargs: object
) -> DynamicConf:
    warn(
        "Objconf is deprecated; use riko.ext.config.DynamicConf",
        DeprecationWarning,
        stacklevel=2,
    )
    return DynamicConf(values, *args, **kwargs)


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


# TODO: move back to meza
@overload
def listize[T](value: list[T]) -> list[T]: ...  # noqa: E704
@overload  # noqa: E302
def listize[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: dict[str, T],
) -> list[dict[str, T]]: ...
@overload  # noqa: E302
def listize[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: CaseInsensitiveDict[T],
) -> list[CaseInsensitiveDict[T]]: ...
@overload
def listize[T](value: Mapping[str, T]) -> list[Mapping[str, T]]: ...  # noqa: E704
@overload  # noqa: E302
def listize[T](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: Sequence[T],
) -> Sequence[T]: ...
@overload
def listize[T](value: Iterable[T]) -> Iterable[T]: ...  # noqa: E704
@overload
def listize[T](value: T) -> list[T]: ...  # noqa: E704
def listize[T](value: T) -> T | Iterable[T]:  # noqa: E302
    """
    Create a listlike object from any value

    Args:
        value: The object to convert

    Returns:
        value as a listlike object (wrapped in a list or the value itself)

    Examples:
    >>> listize(x for x in range(3))  # doctest: +ELLIPSIS
    <generator object <genexpr> at 0x...>
    >>> listize([x for x in range(3)])
    [0, 1, 2]
    >>> listize(iter(x for x in range(3)))  # doctest: +ELLIPSIS
    <generator object <genexpr> at 0x...>
    >>> listize(range(3))
    range(0, 3)

    """
    if not value:
        result = []
    elif isinstance(value, (PrimitiveValueType, dict, CaseInsensitiveDict, Mapping)):
        result = [value]
    elif isinstance(value, (Iterable, Sequence)):
        result = value
    else:
        result = [value]

    return result


from riko.api import (  # noqa: E402
    AsyncCollection,
    AsyncPipe,
    PipelineStateError,
    PipeState,
    SyncCollection,
    SyncPipe,
    UnsupportedModuleError,
    UnsupportedPipelineError,
    export,
    list_modules,
    list_targets,
)

__all__ = [
    "AsyncCollection",
    "AsyncPipe",
    "Context",
    "ExecutionMode",
    "PipeState",
    "PipelineStateError",
    "SyncCollection",
    "SyncPipe",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "export",
    "list_modules",
    "list_targets",
]
