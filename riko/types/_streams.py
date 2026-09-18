"""Synchronous and asynchronous item and stream typing aliases."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterable, Iterator
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from riko.parsing._dotdict import DotDict

    from ._collections import RikoDict, RikoValue
    from ._rss import RSSEntry
    from ._sentinels import StreamState

# Parser values
type Record = RikoDict | dict[str, RikoValue] | RSSEntry | DotDict[RikoValue]
type RecordOrValue = Record | RikoValue


class StatefulItem(TypedDict):
    state: StreamState


# Parser sync
type Records = Iterable[Record]
type RecordsOrValues = Iterable[RecordOrValue]
type RecordStream = Iterator[Record]
type ValueStream = Iterator[RikoValue]
type RecordOrValueStream = Iterator[RecordOrValue]
type Streams = Iterator[RecordStream]

# Parser async
type AsyncRecords = AsyncIterable[Record]
type AsyncRecordsOrValues = AsyncIterable[RecordOrValue]
type AsyncRecordStream = AsyncIterator[Record]
type AsyncRecordOrValueStream = AsyncIterator[RecordOrValue]
type RecordFeed = AsyncRecords
type RecordSource = Records | RecordFeed | Awaitable[Records | RecordFeed]

# Pipe/wrapper
type Item = RecordOrValue | RecordStream
type Items = Iterable[Item]
type Stream = Iterator[Item]

type Feed = AsyncIterable[Item]
type AsyncStream = AsyncIterator[Item]
type Source = Items | Feed | Awaitable[Items | Feed]

# Operator `others` — pipe names or streams (sync or async) to merge or reference
type OthersLike = Iterable[str] | Iterable[Stream] | Iterable[AsyncStream] | None
