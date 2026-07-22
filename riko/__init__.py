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
from importlib.metadata import metadata, version
from os import path as p
from time import struct_time
from typing import TYPE_CHECKING, Literal, TypeVar, overload

from meza.fntools import Objectify as _Objectify
from requests.structures import CaseInsensitiveDict

from riko.context import Context, ExecutionMode  # noqa: F401
from riko.types.general import ItemOrValue, SyncArgFunc
from riko.types.modules import AnyConfRule, ObjconfParam
from riko.types.values import PrimitiveValue, PrimitiveValueType

# https://github.com/astral-sh/uv/issues/7533#issuecomment-2472804995
meta = metadata("riko")

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


def get_path(name: str):
    if name.startswith(("http", "file:")):
        url = name
    else:
        url = f"file://{p.join(PARENT_DIR, 'data', name)}"

    return url


def get_abspath(url: str, offline=False) -> str:
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


def replacer(content: str, old: str, new="_") -> str:
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


class Objectify(_Objectify, Mapping[str, VT]):
    """
    Creates an object with dynamically set attributes. Useful
    for accessing the kwargs of a function as attributes.
    """

    def __init__(self, data: Mapping[str, VT], *args, **kwargs):
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

    def __len__(self) -> int:
        return len(self.data)

    if TYPE_CHECKING:

        def __getattribute__(self, *_) -> VT: ...  # noqa: E704
        def __getitem__(self, *_) -> VT: ...  # noqa: E704
        def __iter__(self) -> Iterator[str]: ...  # noqa: E704
        def iteritems(self) -> Iterator[tuple[str, VT]]: ...  # noqa: E704


class Objconf(Objectify):
    assign: str
    attrs: list[str]
    base: str
    col_names: list[str]
    combine: Literal["and", "or"]
    count: str | int
    currency: str
    debug: bool
    default: PrimitiveValue
    delay: int
    delimiter: str
    detag: bool
    emit: bool
    encoding: str
    end: str
    ext: str
    format: str
    group_key: str
    html5: bool
    join_key: str
    length: int
    limit: int
    lower: bool
    max_len: int
    max_wait: float
    multi: bool
    name: str
    other: str
    op: str
    other_join_key: str
    param: ObjconfParam | list[ObjconfParam]
    parse_key: str
    part: str
    path: str | list[str]
    permit: bool
    precision: int
    prompt: str
    rule: AnyConfRule | list[AnyConfRule]
    skip_rows: int
    sort: int
    start: str | int
    stop: str | int
    strict: bool
    stringify: bool
    sum_key: str
    times: int
    token: str
    token_key: str
    type: str
    uniq_key: str
    url: str
    wait: float
    xpath: str


@overload
def objectify(data: Mapping) -> Objectify: ...  # noqa: E704
@overload  # noqa: E302
def objectify[T](data: T) -> T: ...  # noqa: E704
@overload  # noqa: E302
def objectify(  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    data: Mapping, func: SyncArgFunc
) -> Objectify: ...
@overload  # noqa: E302
def objectify[T](  # noqa: E704
    data: Sequence[T], func: SyncArgFunc
) -> list[ItemOrValue | Objectify]: ...
@overload  # noqa: E302
def objectify(  # noqa: E704
    data: object, func: SyncArgFunc
) -> ItemOrValue: ...
def objectify[T](  # noqa: E302
    data: T, func: SyncArgFunc | None = None, **defaults
) -> T | ItemOrValue | Objectify | list[T] | list[ItemOrValue | Objectify]:
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
    "SyncCollection",
    "SyncPipe",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "export",
    "list_modules",
    "list_targets",
]
