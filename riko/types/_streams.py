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
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, TypeGuard

from typing_extensions import TypeVar

from riko.base._guards import is_mapping
from riko.base._sentinels import StreamState

from ._geo import AnyLocation

if TYPE_CHECKING:
    from riko.parsing._dotdict import DotDict

    from ._rss import RSSEntry
    from ._values import RikoDict, RikoValue, StringyDict


# Item/value
class StatefulItem(TypedDict):
    state: StreamState


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
)

type ItemOrValue = Item | RikoValue
type ItemValue = ItemOrValue | list[ItemOrValue]

# Sync
type Stream = Iterator[Item]
type Cascade = Iterator[Stream]
type ItemOrStream = Item | Stream

type Items = Iterable[Item]
type Streams = Iterable[Stream]
type ItemsOrValues = Iterable[ItemOrValue]

type ValueStream = Iterator[RikoValue]
type StreamOrValueStream = Iterator[ItemOrValue]
type ItemGenerator = Generator[Item, None]

# Async
type AsyncStream = AsyncIterator[Item]
type AsyncCascade = AsyncIterator[Stream]
type AsyncItemOrStream = ItemOrStream | AsyncStream

type AsyncItems = AsyncIterable[Item]
type AsyncStreams = AsyncIterable[Stream]
type AsyncItemsOrValues = AsyncIterable[ItemOrValue]

type AsyncStreamOrValueStream = AsyncIterator[ItemOrValue]
type AsyncItemGenerator = AsyncGenerator[Item, None]
type StreamGenerator = Generator[Any, None, Stream]

# Both
type AnyIterable[T] = Iterable[T] | AsyncIterable[T]
type Feed = AnyIterable[Item]
type InputLike = Item | Feed | Awaitable[Item | Feed]
type OthersLike = Iterable[str | AsyncStream] | Streams | AsyncStreams


def is_stateful_item(val: Item) -> TypeGuard[StatefulItem]:
    return isinstance(val.get("state"), StreamState) if is_mapping(val) else False


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

    def __aiter__(self) -> AsyncIterator[T_co]: ...
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
    async def __aenter__(self) -> AsyncIterator[T_co]: ...
    async def __aexit__(self, *exc: object) -> None: ...
