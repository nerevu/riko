"""Synchronous and asynchronous item and stream typing aliases."""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Generator,
    Iterable,
    Iterator,
)
from typing import TYPE_CHECKING, Protocol, TypedDict, TypeGuard

from typing_extensions import TypeVar

from riko.base._guards import is_mapping
from riko.base._sentinels import StreamState

from ._geo import AnyLocation

if TYPE_CHECKING:
    from riko.parsing._dotdict import DotDict

    from ._rss import RSSEntry
    from ._scalars import DateDict
    from ._values import RikoDict, RikoValue, StringyDict

type Item = (
    RikoDict
    | dict[str, RikoValue]
    | dict[str, ItemValue]
    | RSSEntry
    | StatefulItem
    | DotDict[RikoValue]
    | DotDict[ItemValue]
    | AnyLocation
    | StringyDict
    | DateDict
)

type ItemOrValue = Item | RikoValue
type ItemValue = ItemOrValue | list[ItemOrValue]

# Sync
type StreamOf[T] = Iterator[T]
type Stream = StreamOf[Item]
type CascadeOf[T] = StreamOf[StreamOf[T]]
type Cascade = CascadeOf[Item]
type ItemOrStream = Item | Stream
type Items = Iterable[Item]
type Streams = Iterable[Stream]
type ItemsOrValues = Iterable[ItemOrValue]
type ValueStream = StreamOf[RikoValue]
type StreamOrValueStream = StreamOf[ItemOrValue]
type ItemGenerator = Generator[Item, None]

# Async
type AsyncStreamOf[T] = AsyncIterator[T]
type AsyncStream = AsyncStreamOf[Item]
type AsyncCascadeOf[T] = AsyncStreamOf[AsyncStreamOf[T]]
type AsyncCascade = AsyncCascadeOf[Item]
type AsyncItems = AsyncIterable[Item]
type AsyncStreams = AsyncIterable[Stream]
type AsyncItemsOrValues = AsyncIterable[ItemOrValue]
type AsyncStreamOrValueStream = AsyncStreamOf[ItemOrValue]
type AsyncItemGenerator = AsyncGenerator[Item, None]

# Both
type AnyIterable[T] = Iterable[T] | AsyncIterable[T]
type Feed = AnyIterable[Item]
type ValueFeed = AnyIterable[ItemValue]
type InputLike = Item | ValueFeed | Awaitable[Item | ValueFeed]


# Item/value
class StatefulItem(TypedDict):
    state: StreamState


def is_stateful_item(val: Item) -> TypeGuard[StatefulItem]:
    return isinstance(val.get("state"), StreamState) if is_mapping(val) else False


def require_stream[T](value: Iterable[T], name: str) -> StreamOf[T]:
    """
    Requires ``value`` to be an iterator.

    Args:

        value: An iterable.
        name: Name of the module that returned ``value``.

    Returns:

        ``value`` typed as an iterator.

    Raises:

        TypeError: If ``value`` isn't an iterator.

    Examples:

        >>> next(require_stream(iter([1]), "count"))
        1
        >>> require_stream([1], "count")
        Traceback (most recent call last):
        ...
        TypeError: module 'count' returned a list. A pipe must return an iterator...

    """
    if not isinstance(value, Iterator):
        kind = type(value).__name__
        msg = f"module {name!r} returned a {kind}. A pipe must return an iterator "
        raise TypeError(msg + "(wrap it in iter(...))")

    return value


def _build_async_stream_error(value: object, name: str) -> TypeError:
    """Builds the error for an async pipe output that isn't an async iterator."""
    kind = type(value).__name__
    msg = f"module {name!r} returned a {kind}. An async_pipe must return an async "
    return TypeError(msg + "iterator (an async def generator)")


def require_async_stream[T](value: AnyIterable[T], name: str) -> AsyncStreamOf[T]:
    """
    Requires ``value`` to be an async iterator.

    Args:

        value: A sync or async iterable.
        name: Name of the module that returned ``value``.

    Returns:

        ``value`` typed as an async iterator.

    Raises:

        TypeError: If ``value`` isn't an async iterator.

    Examples:

        >>> from riko.bado.itertools import as_async
        >>>
        >>> stream = require_async_stream(as_async([1]), "count")
        >>> require_async_stream([1], "count")
        Traceback (most recent call last):
        ...
        TypeError: module 'count' returned a list. An async_pipe must return an async...

    """
    if not isinstance(value, AsyncIterator):
        raise _build_async_stream_error(value, name)

    return value


def require_any_stream[T](
    value: AnyIterable[T], name: str
) -> StreamOf[T] | AsyncStreamOf[T]:
    """
    Requires ``value`` to be a sync or async iterator.

    Args:

        value: A sync or async iterable.
        name: Name of the module that returned ``value``.

    Returns:

        ``value`` typed as a sync or an async iterator.

    Raises:

        TypeError: If ``value`` is neither a sync nor an async iterator.

    Examples:

        >>> next(require_any_stream(iter([1]), "count"))
        1
        >>> require_any_stream([1], "count")
        Traceback (most recent call last):
        ...
        TypeError: module 'count' returned a list. An async_pipe must return an async...

    """
    if not isinstance(value, (Iterator, AsyncIterator)):
        raise _build_async_stream_error(value, name)

    return value


T_co = TypeVar("T_co", covariant=True, default=Item)


class PipelineStream(Protocol[T_co]):
    """
    One single-use pipeline run that can be iterated with ``for`` or ``async for``.

    ``pipeline(items)`` returns a stream that is its own iterator: once consumed or
    closed, another ``for`` loop yields nothing and ``next(stream, default)`` returns
    ``default``. Use ``pipeline.open(items)`` instead to return a context manager that
    closes the run on exit.
    """

    def __iter__(self) -> Iterator[T_co]: ...
    def __next__(self) -> T_co: ...

    def close(self) -> None:
        """Stops the run and releases its resources (closing again does nothing)."""
        ...

    def __aiter__(self) -> AsyncStreamOf[T_co]: ...
    async def __anext__(self) -> T_co: ...

    async def aclose(self) -> None:
        """Stops an asynchronous run and releases its resources."""
        ...


class PipelineRun(Protocol[T_co]):
    """
    A context manager over one pipeline run that closes the run on exit.

    ``pipeline.open(items)`` returns a run: ``with`` yields a synchronous iterator and
    ``async with`` an asynchronous one. Leaving the block (by exhaustion, ``break``, or
    an exception) closes the run in the task that opened it.
    """

    def __enter__(self) -> Iterator[T_co]: ...
    def __exit__(self, *exc: object) -> None: ...
    async def __aenter__(self) -> AsyncStreamOf[T_co]: ...
    async def __aexit__(self, *exc: object) -> None: ...
