"""RSS and Atom entry typing contracts."""

from __future__ import annotations

from time import struct_time
from typing import Literal, Protocol, Required, TypedDict, overload

type RSSEntry = ExpandedRSSEntry | YahooRSSEntry | AugmentedRSSEntry


class EntryContent(TypedDict, total=False):
    value: Required[str]
    type: str
    language: str
    base: str


class Enclosure(TypedDict):
    type: str
    length: int
    href: str


class AuthorDetail(TypedDict):
    href: str
    name: str
    email: str


class CommonRSSEntry(TypedDict, total=False):
    link: Required[str]
    author: str | None
    title: str | None
    description: str | None
    content: list[EntryContent]
    enclosures: list[Enclosure]
    published: str | None
    updated: str | None


class FeedParserRSSEntry(CommonRSSEntry, total=False):
    id: str | None
    summary: str | None
    author_detail: AuthorDetail
    published_parsed: struct_time | None
    updated_parsed: struct_time | None


class ExpandedRSSEntry(FeedParserRSSEntry):
    pubDate: struct_time | None


class FasterFeedParserRSSEntry(CommonRSSEntry, total=False):
    media_content: list[EntryContent]


class ParserRSSEntry(FeedParserRSSEntry, FasterFeedParserRSSEntry, total=False):
    """A feed entry as either supported feed parser returns it."""


YahooRSSEntry = TypedDict(
    "YahooRSSEntry",
    {
        "author.name": str | None,
        "author.uri": str | None,
        "dc:creator": str | None,
        "y:id": str | None,
        "y:published": str | struct_time | None,
        "y:title": str | None,
    },
)


class AugmentedRSSEntry(ParserRSSEntry, ExpandedRSSEntry, YahooRSSEntry):
    """A parsed feed entry with the Yahoo! Pipes fields and date aliases filled in."""


class ParsedFeed(Protocol):
    """A parsed feed: its entries plus feed-level keys such as ``bozo``."""

    @overload
    def __getitem__(self, key: Literal["entries"], /) -> list[ParserRSSEntry]: ...
    @overload
    def __getitem__(self, key: str, /) -> object: ...
    def get(self, key: str, /) -> object: ...
