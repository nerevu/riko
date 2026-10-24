"""Sequence normalization and fluent application helpers."""

from __future__ import annotations

import builtins
import itertools
from collections.abc import Sequence
from functools import partial
from inspect import signature
from itertools import repeat
from time import struct_time
from typing import TYPE_CHECKING, Any, Self, cast, overload

from riko.base._guards import is_known_sequence, is_listlike, is_mapping
from riko.base._iterutils import map_values, multi_try

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from requests.structures import CaseInsensitiveDict

    from riko.types._streams import Item, Stream, StreamOrValueStream, ValueStream
    from riko.types._values import BasicDict, RikoValue, StringyDict


@overload
def listize(  # pyright: ignore[reportOverlappingOverload]
    value: Item | Iterable[Item],
) -> Iterable[Item]: ...
@overload
def listize[T](value: list[T]) -> list[T]: ...
@overload
def listize[T](value: dict[str, T]) -> list[dict[str, T]]: ...
@overload
def listize[T](value: CaseInsensitiveDict[T]) -> list[CaseInsensitiveDict[T]]: ...
@overload
def listize[T](value: Mapping[str, T]) -> list[Mapping[str, T]]: ...
@overload
def listize[T](value: Sequence[T]) -> Sequence[T]: ...
@overload
def listize[T](value: Iterable[T]) -> Iterable[T]: ...
@overload
def listize[T](value: T) -> list[T]: ...
def listize[T](value: T) -> T | Iterable[T]:
    """
    Creates a listlike object from any value.

    Args:

        value: The object to convert.

    Returns:

        ``value`` as a listlike object (wrapped in a list, or itself).

    Examples:

        >>> generator = (x for x in range(3))
        >>> listize(generator) is generator
        True
        >>> values = [x for x in range(3)]
        >>> listize(values) is values
        True
        >>> listize(range(3))
        range(0, 3)
        >>> listize(0)
        [0]
        >>> listize(False)
        [False]
        >>> listize("")
        ['']
        >>> listize(None)
        []

    """
    if value is None:
        result = []
    elif is_listlike(value):
        result = value
    else:
        result = [value]

    return result


@overload
def gen_items(content: BasicDict | StringyDict, key: str | None = ...) -> Stream: ...
@overload
def gen_items(content: RikoValue) -> ValueStream: ...
@overload
def gen_items(content: RikoValue, key: str, yield_if_none: bool = ...) -> Stream: ...
@overload
def gen_items(
    content: RikoValue, key: None = ..., yield_if_none: bool = ...
) -> ValueStream: ...
def gen_items(
    content: RikoValue | BasicDict | StringyDict,
    key: str | None = None,
    yield_if_none=False,
) -> StreamOrValueStream:
    """
    Flattens nested Riko values into a stream of values or keyed items.

    Args:

        content: Scalar, mapping, or nested list/tuple content to emit.
        key: Optional field name used to wrap each emitted value in a mapping.
        yield_if_none: Whether a top-level ``None`` should be emitted.

    Yields:

        Flattened values, or mappings of ``key`` to each value when ``key`` is set.

    Examples:

        >>> list(gen_items([1, [2, 3]]))
        [1, 2, 3]
        >>> list(gen_items({"a": 1}, key="value"))
        [{'value': {'a': 1}}]
        >>> list(gen_items(None, yield_if_none=True))
        [None]

    """
    if isinstance(content, struct_time) or is_mapping(content):
        yield {key: content} if key else content
    elif is_known_sequence(content):
        for value in content:
            yield from gen_items(value, key)
    elif content is not None or yield_if_none:
        yield {key: content} if key else content


def truncate_content[T](content: T | object, length: int = 20) -> T:
    """
    Shortens every string or bytes value for a log message, recursing into containers.

    Args:

        content: A string, bytes, a mapping or sequence of values, or any other value.
        length: The longest a string or bytes value stays before it is cut and marked
            with "…".

    Returns:

        The shortened value; a value with nothing to shorten is returned as is.

    Examples:

        >>> truncate_content({"a": "x" * 30, "n": 5}, length=4)
        {'a': 'xxxx…', 'n': 5}
        >>> truncate_content(b"x" * 30, length=4)
        b'xxxx\xe2\x80\xa6'

    """
    if isinstance(content, str):
        truncated = content[:length] + "…" if len(content) > length else content
    elif isinstance(content, bytes):
        truncated = (
            content[:length] + "…".encode() if len(content) > length else content
        )
    elif is_mapping(content):
        truncated = map_values(partial(truncate_content, length=length), content)
    elif isinstance(content, Sequence):
        truncated = [truncate_content(v, length) for v in content]
    else:
        truncated = content

    return cast("T", truncated)


class Chainable:
    """
    A fluent wrapper that resolves and applies methods across namespaces.

    Attribute access looks the name up on the wrapped data, then ``builtins``,
    then ``itertools``, and returns a new ``Chainable`` bound to the found method.
    Calling it applies the method with the data as the first argument when the
    method's signature accepts it there, else as the second.

    Examples:

        >>> Chainable([3, 1, 2]).sorted().data
        [1, 2, 3]

    """

    data: object
    method: Callable | None
    list: builtins.list[object]

    def __init__(self, data: object, method: Callable | None = None) -> None:
        self.data = data
        self.method = method
        self.list = listize(data)

    def __getattr__(self, name: str) -> Self:
        funcs = (partial(getattr, x) for x in [self.data, builtins, itertools])
        zipped = zip(funcs, repeat(AttributeError), strict=False)
        method = multi_try(name, zipped, default=None)
        result = Chainable(self.data, method)
        return cast("Self", result)

    def __call__(self, *args: Any, **kwargs: object) -> Self:
        method = self.method

        if method is None:
            result = Chainable(self.data)
        else:
            try:
                signature(method).bind(self.data, *args, **kwargs)
                data_first = True
            except TypeError:
                data_first = False
            except ValueError:
                data_first = True

            if data_first or not args:
                result = Chainable(method(self.data, *args, **kwargs))
            else:
                result = Chainable(method(args[0], self.data, **kwargs))

        return cast("Self", result)
