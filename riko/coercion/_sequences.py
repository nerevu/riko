"""Sequence normalization and fluent application helpers."""

from __future__ import annotations

import builtins
import itertools
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import partial
from inspect import signature
from itertools import repeat
from time import struct_time
from typing import TYPE_CHECKING, Any, Self, TypeGuard, cast, overload

from requests.structures import CaseInsensitiveDict

from riko.base._iterutils import multi_try
from riko.base.exceptions import InvalidPipelineError
from riko.types._scalars import PrimitiveValueType

if TYPE_CHECKING:
    from riko.types._collections import BasicDict, RikoValue, StringyDict
    from riko.types._streams import Item, Stream, StreamOrValueStream, ValueStream


def is_listlike[T](value: Iterable[T] | object) -> TypeGuard[Iterable[T]]:
    """
    Reports whether a value is listlike (a multi-item iterable).

    A listlike value is any iterable that is not a mapping, primitive, or ``None``.

    Args:

        value: The object to classify.

    Returns:

        True when ``value`` maps over items, False when it is one item.

    Examples:

        >>> is_listlike([1, 2])
        True
        >>> is_listlike((1, 2))
        True
        >>> is_listlike(iter([1, 2]))
        True
        >>> is_listlike(range(3))
        True
        >>> is_listlike({"a": 1})
        False
        >>> is_listlike("ab")
        False
        >>> is_listlike(0)
        False
        >>> is_listlike(None)
        False

    """
    if value is None or isinstance(
        value, (PrimitiveValueType, bytes, dict, CaseInsensitiveDict, Mapping)
    ):
        result = False
    else:
        result = isinstance(value, Iterable)

    return result


def require_sequence(value: object, what: str) -> Iterable[object]:
    """Narrows a value to a non-string iterable or rejects it."""
    if not is_listlike(value):
        raise InvalidPipelineError(f"{what} must be a list")

    return value


# TODO: move back to meza
@overload
def listize(  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
    value: Item | Iterable[Item],
) -> Iterable[Item]: ...
@overload
def listize[T](value: list[T]) -> list[T]: ...  # noqa: E704
@overload  # noqa: E302
def listize[T](  # noqa: E704
    value: dict[str, T],
) -> list[dict[str, T]]: ...
@overload  # noqa: E302
def listize[T](  # noqa: E704
    value: CaseInsensitiveDict[T],
) -> list[CaseInsensitiveDict[T]]: ...
@overload
def listize[T](value: Mapping[str, T]) -> list[Mapping[str, T]]: ...  # noqa: E704
@overload  # noqa: E302
def listize[T](  # noqa: E704
    value: Sequence[T],
) -> Sequence[T]: ...
@overload
def listize[T](value: Iterable[T]) -> Iterable[T]: ...  # noqa: E704
@overload
def listize[T](value: T) -> list[T]: ...  # noqa: E704
def listize[T](value: T) -> T | Iterable[T]:  # noqa: E302
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
def gen_items(  # noqa: E704
    content: BasicDict | StringyDict, key: str | None = ...
) -> Stream: ...
@overload
def gen_items(content: RikoValue) -> ValueStream: ...  # noqa: E704
@overload  # noqa: E302
def gen_items(  # noqa: E704
    content: RikoValue, key: str, yield_if_none: bool = ...
) -> Stream: ...  # noqa: E704
@overload  # noqa: E302
def gen_items(  # noqa: E704
    content: RikoValue, key: None = ..., yield_if_none: bool = ...
) -> ValueStream: ...
def gen_items(  # noqa: E302
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
    if isinstance(content, (struct_time, dict, CaseInsensitiveDict)):
        yield {key: content} if key else content
    elif isinstance(content, (list, tuple)):
        for value in content:
            yield from gen_items(value, key)
    elif content is not None or yield_if_none:
        yield {key: content} if key else content


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
