from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterable, Iterator
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from riko.dotdict import DotDict

    from ._collections import RikoDict, RikoValue
    from ._rss import RSSEntry
    from ._sentinels import StreamState


type Item = RikoDict | dict[str, RikoValue] | RSSEntry | DotDict[RikoValue]
type ItemOrValue = Item | RikoValue
type Items = Iterable[Item]
type ItemsOrValues = Iterable[ItemOrValue]
type ValueStream = Iterator[RikoValue]
type Stream = Iterator[Item]
type StreamOrValueStream = Iterator[ItemOrValue]
type Streams = Iterator[Stream]

type AsyncItems = AsyncIterable[Item]
type AsyncItemsOrValues = AsyncIterable[ItemOrValue]
type AsyncStream = AsyncIterator[Item]
type AsyncStreamOrValueStream = AsyncIterator[ItemOrValue]

type Feed = AsyncItems
type AsyncSource = Items | Feed | Awaitable[Items | Feed]


class StatefulItem(TypedDict):
    state: StreamState
