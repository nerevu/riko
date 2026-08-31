from __future__ import annotations

from time import struct_time
from typing import TYPE_CHECKING, Required, TypedDict

if TYPE_CHECKING:
    from fastfeedparser import FastFeedParserDict
    from feedparser import FeedParserDict


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


type ParserRSSEntry = FeedParserRSSEntry | FasterFeedParserRSSEntry

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

type RSSEntry = ExpandedRSSEntry | YahooRSSEntry
type RSSParseResult = FeedParserDict | FastFeedParserDict
