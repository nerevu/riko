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

from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from importlib.metadata import metadata, version
from os import path as p
from time import struct_time
from typing import TYPE_CHECKING, Any, Literal, TypeVar, overload

from meza import compat
from meza.fntools import Objectify as _Objectify

from riko.types.general import SyncItemFunc
from riko.types.modules import AnyConfRule, ObjconfParam
from riko.types.values import (
    BasicArg,
    BasicMapping,
    BasicSequence,
    ComplexArg,
    ComplexMapping,
    IntermediateValue,
    IntermediateValueType,
)

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

T = TypeVar("T", bound=ComplexArg)
KT = TypeVar("KT")


def get_path(name: str):
    if name.startswith(("http", "file:")):
        url = name
    else:
        url = f"file://{p.join(PARENT_DIR, 'data', name)}"

    return url


def get_abspath(url: str, offline=False):
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

    return compat.decode(url)


def replacer(content: str, old: str, new="_") -> str:
    if old:
        replaced = content.replace(old, new)
    elif content[0].isdecimal() or not content[0].isascii():
        replaced = f"{new}{content}"
    else:
        replaced = content

    return replaced


class Context:
    """
    The context of a pipeline
    verbose = debug printing during compilation and running
    describe_input = return pipe input requirements
    describe_dependencies = return a list of sub-pipelines used
    test = takes input values from default (skips the console prompt)
    inputs = a dictionary of values that overrides the defaults
        e.g. {'name one': 'test value1'}
    submodule = takes input values from inputs (or default)
    """

    def __init__(self, **kwargs):
        self.verbose = kwargs.get("verbose", False)
        self.test = kwargs.get("test", False)
        self.describe_input = kwargs.get("describe_input", False)
        self.describe_dependencies = kwargs.get("describe_dependencies", False)
        self.inputs = kwargs.get("inputs", {})
        self.submodule = kwargs.get("submodule", False)

    def __repr__(self):
        content = f"verbose={self.verbose}, test={self.test}, "
        content += f"describe_input={self.describe_input}, "
        content = f"describe_dependencies={self.describe_dependencies}, "
        content = f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"


class Objectify(_Objectify):
    """
    Creates an object with dynamically set attributes. Useful
    for accessing the kwargs of a function as attributes.
    """

    def __init__(self, data: ComplexMapping, *args, **kwargs):
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

    if TYPE_CHECKING:

        def __getattribute__(self, name: str) -> BasicArg: ...  # noqa: E704
        def __getitem__(self, name: str) -> BasicArg: ...  # noqa: E704
        def __iter__(self) -> Iterator[str]: ...  # noqa: E704
        def iteritems(self) -> Iterator[tuple[str, BasicArg]]: ...  # noqa: E704


class Objconf(Objectify):
    assign: str
    attrs: Sequence[str]
    base: str
    col_names: Sequence[str]
    combine: Literal["and", "or"]
    count: str | int
    currency: str
    debug: bool
    default: BasicArg
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
    max_wait: int
    multi: bool
    name: str
    other: str
    op: str
    other_join_key: str
    param: ObjconfParam | Sequence[ObjconfParam]
    parse_key: str
    part: str
    path: str | list[str]
    permit: bool
    precision: int
    prompt: str
    rule: AnyConfRule | Sequence[AnyConfRule]
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
    wait: int
    xpath: str


@overload
def objectify(  # noqa: E704
    data: Mapping, func: SyncItemFunc | None = None, **defaults
) -> Objectify: ...
@overload  # noqa: E302
def objectify(  # noqa: E704
    data: Sequence, func: SyncItemFunc, **defaults
) -> list[ComplexArg]: ...
@overload  # noqa: E302
def objectify(  # noqa: E704
    data: ComplexArg, func: SyncItemFunc | None = None, **defaults
) -> ComplexArg: ...
def objectify(  # noqa: E302
    data: ComplexArg, func: SyncItemFunc | None = None, **defaults
) -> ComplexArg:
    if isinstance(data, Mapping):
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
def listize(value: BasicMapping) -> list[BasicMapping]: ...  # noqa: E704
@overload
def listize(value: Mapping[KT, T]) -> list[Mapping[KT, T]]: ...  # noqa: E704
@overload
def listize(value: Callable[..., T]) -> list[Callable[..., T]]: ...  # noqa: E704
@overload
def listize(value: IntermediateValue) -> list[IntermediateValue]: ...  # noqa: E704
@overload
def listize(value: BasicSequence) -> BasicSequence: ...  # noqa: E704
@overload
def listize(value: list[T]) -> list[T]: ...  # noqa: E704
@overload
def listize(value: Sequence[T]) -> Sequence[T]: ...  # noqa: E704
@overload  # noqa: E302
def listize(  # noqa: E704
    value: Generator[T, None, None],
) -> Generator[T, None, None]: ...
@overload
def listize(value: Iterator[T]) -> Iterator[T]: ...  # noqa: E704
@overload
def listize(value: Iterable[T]) -> Iterable[T]: ...  # noqa: E704
@overload
def listize(value: Any) -> list[Any] | Iterable | Sequence: ...  # noqa: E704
def listize(  # noqa: E302
    value: Any,
) -> list[Mapping | IntermediateValue | Callable] | Iterable | Sequence:
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
    elif isinstance(value, (Mapping, IntermediateValue, Callable)):
        result = [value]
    elif isinstance(value, (Iterable, Sequence)):
        result = value
    else:
        result = [value]

    return result
