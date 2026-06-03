# -*- coding: utf-8 -*-
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
from os import path as p
from importlib.metadata import version, metadata
from time import struct_time
from typing import Any, Callable, Generator, Iterable, Iterator, Literal, Mapping, Optional, Sequence, TypeVar, cast as cast_type, overload

from meza import compat
from meza.fntools import Objectify as _Objectify

from riko.types.general import ComplexArg, BasicArg, ComplexMapping, IntermediateValue, ObjconfParam, ObjconfRule, SyncItemFunc

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


def get_path(name: str):
    if name.startswith("http") or name.startswith("file:"):
        url = name
    else:
        url = f"file://{p.join(PARENT_DIR, "data", name)}"

    return url


def get_abspath(url: str, offline=False):
    if url.startswith("http"):
        pass
    elif url.startswith("file:///"):
        pass
    elif url.startswith("file://"):
        parent = p.dirname(p.dirname(__file__))
        rel_path = url[7:]
        abspath = p.abspath(p.join(parent, rel_path))
        url = "file://%s" % abspath
    elif offline:
        url = get_path(url)
    else:
        url = "http://%s" % url if url and "://" not in url else url

    return compat.decode(url)


def replacer(content: str, old: str, new="_") -> str:
    if old:
        replaced = content.replace(old, new)
    elif content[0].isdecimal() or not content[0].isascii():
        replaced = f"{new}{content}"
    else:
        replaced = content

    return replaced


class Context(object):
    """The context of a pipeline
        verbose = debug printing during compilation and running
        describe_input = return pipe input requirements
        describe_dependencies = return a list of sub-pipelines used
        test = takes input values from default (skips the console prompt)
        inputs = a dictionary of values that overrides the defaults
            e.g. {'name one': 'test value1'}
        submodule = takes input values from inputs (or default)
    """

    def __init__(self, **kwargs):
        self.verbose = kwargs.get('verbose', False)
        self.test = kwargs.get('test', False)
        self.describe_input = kwargs.get('describe_input', False)
        self.describe_dependencies = kwargs.get('describe_dependencies', False)
        self.inputs = kwargs.get('inputs', {})
        self.submodule = kwargs.get('submodule', False)

    def __repr__(self):
        content = f"verbose={self.verbose}, test={self.test}, "
        content += f"describe_input={self.describe_input}, "
        content = f"describe_dependencies={self.describe_dependencies}, "
        content = f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"


class Objectify(_Objectify):
    """Creates an object with dynamically set attributes. Useful
    for accessing the kwargs of a function as attributes.
    """

    def __init__(self, data: ComplexMapping, *args, **kwargs):
        """Objectify constructor

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

    def __getattribute__(self, name: str) -> BasicArg:
        return super().__getattribute__(name)

    def __getitem__(self, name: str) -> BasicArg:
        item = super().__getitem__(name)
        return cast_type(BasicArg, item)

    def __iter__(self) -> Iterator[str]:
        return super().__iter__()

    def iteritems(self) -> Iterator[tuple[str, BasicArg]]:
        return super().iteritems()


class Objconf(Objectify):
    assign: str
    attrs: Sequence[str]
    base: str
    col_names: Sequence[str]
    combine: Literal["and", "or"]
    count: str
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
    prompt: str
    rule: ObjconfRule | Sequence[ObjconfRule]
    skip_rows: int
    sort: int
    start: int
    stop: str
    strict: bool
    stringify: bool
    sum_key: str
    times: int
    token: str
    token_key: str
    type: str
    unique_key: str
    url: str
    wait: int
    xpath: str


def objectify(data: ComplexArg, func: Optional[SyncItemFunc] = None, **defaults) -> ComplexArg:
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
K = TypeVar("K")
T = TypeVar("T")


@overload
def listize(value: Mapping[K, T]) -> list[Mapping[K, T]]:
    ...
@overload  # noqa: E302
def listize(value: Callable[..., T]) -> list[Callable[..., T]]:
    ...
@overload  # noqa: E302
def listize(value: IntermediateValue) -> list[IntermediateValue]:
    ...
@overload  # noqa: E302
def listize(value: list[T]) -> list[T]:
    ...
@overload  # noqa: E302
def listize(value: Sequence[T]) -> Sequence[T]:
    ...
@overload  # noqa: E302
def listize(value: Generator[T, None, None]) -> Generator[T, None, None]:
    ...
@overload  # noqa: E302
def listize(value: Iterator[T]) -> Iterator[T]:
    ...
@overload  # noqa: E302
def listize(value: Iterable[T]) -> Iterable[T]:
    ...
def listize(  # noqa: E302
    value: Any
) -> list[Mapping | IntermediateValue | Callable] | Iterable | Sequence:
    """Create a listlike object from any value

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
