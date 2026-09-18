"""Synchronous and asynchronous item and stream typing aliases."""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Generator,
    Iterable,
    Iterator,
)
from typing import TYPE_CHECKING, Any, TypedDict

from riko.base._locations import AnyLocation

from ._collections import StringyDict

if TYPE_CHECKING:
    from riko.parsing._dotdict import DotDict

    from ._collections import RikoDict, RikoValue
    from ._rss import RSSEntry
    from ._sentinels import StreamState


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
type AsyncStreams = Iterable[AsyncStream]
type AsyncItemsOrValues = AsyncIterable[ItemOrValue]

type AsyncStreamOrValueStream = AsyncIterator[ItemOrValue]
type AsyncItemGenerator = AsyncGenerator[Item, None]
type StreamGenerator = Generator[Any, None, Stream]

# Both
type Feed = Items | AsyncItems
type OthersLike = Iterable[str] | Streams | AsyncStreams
