# vim: sw=4:ts=4:expandtab
"""
RSS and Atom feed parsing and entry normalization.

Examples:

    >>> from riko.rss.feeds import parse_rss
    >>>
    >>> content = (
    ...     "<rss version='2.0'><channel><title>Example</title>"
    ...     "<item><title>First</title></item></channel></rss>"
    ... )
    >>> parse_rss(content=content)[0]["title"]
    'First'

"""

from __future__ import annotations

from datetime import date
from datetime import datetime as dt
from time import struct_time
from typing import TYPE_CHECKING, Any, cast, overload
from urllib.error import URLError
from xml.sax import SAXParseException  # noqa: S406

from riko.base._guards import is_mapping
from riko.base._logging import get_logger
from riko.coercion._dates import date_to_tt, resolve_aware_datetime
from riko.coercion._sequences import truncate_content
from riko.io._sync import Fetch
from riko.parsing.documents import IS_FASTFEEDPARSER, rss_parser

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from logging import Logger

    from riko.types._rss import (
        ExpandedRSSEntry,
        ParserRSSEntry,
        RSSEntry,
        YahooRSSEntry,
    )
    from riko.types._scalars import AnyStr
    from riko.types._values import BasicArg

logger: Logger = get_logger(__name__)


# The overloads are so I can call parse_rss(**kwargs) without Pyright complaining.
# https://stackoverflow.com/q/79673094
@overload
def parse_rss(  # noqa: E704
    url: str, *, content: None = ..., **kwargs: BasicArg
) -> list[ParserRSSEntry]: ...
@overload  # noqa: E302
def parse_rss(  # noqa: E704
    *, content: AnyStr, **kwargs: BasicArg
) -> list[ParserRSSEntry]: ...
@overload
def parse_rss(**kwargs: Any) -> list[ParserRSSEntry]: ...  # noqa: E704
def parse_rss(  # noqa: E302
    url: BasicArg = "", *, content: AnyStr | None = None, **kwargs: BasicArg
) -> list[ParserRSSEntry]:
    """
    Fetches or reads an RSS/Atom feed and returns its parsed entries.

    Args:

        url: URL, path, or source string used when ``content`` is not supplied.
        content: Feed content to parse directly instead of fetching ``url``.
        **kwargs: Additional options forwarded to ``Fetch`` when reading ``url``.

    Returns:

        Parsed RSS/Atom entries in source order.

    Examples:

        >>> content = (
        ...     "<rss version='2.0'><channel><title>Example</title>"
        ...     "<item><title>First</title></item></channel></rss>"
        ... )
        >>> entries = parse_rss(content=content)
        >>> len(entries), entries[0]["title"]
        (1, 'First')

    """
    f = None

    if content is None:
        source_name = str(url)

        try:
            f = Fetch(source_name, binary=True, **kwargs)
        except URLError:
            source, source_name = source_name, "content"
        else:
            if f.file and IS_FASTFEEDPARSER:
                # fastfeedparser.parse takes str/bytes only (no file-like input)
                source = f.read()
            elif f.file:
                source = f.file  # feedparser reads the file object directly
            else:
                source = b""
    else:
        source, source_name = content, "content"

    try:
        parsed = rss_parser.parse(source)
    finally:
        if f:
            f.close()

    bozo = parsed.get("bozo")
    entry_count = len(parsed.entries)

    if bozo is False and not entry_count:
        logger.warning(f"Parsed {source_name} successfully but no entries were found.")
    elif (bozo is False) or (entry_count > 3):
        pass
    elif bozo_exception := parsed.get("bozo_exception"):
        if isinstance(bozo_exception, SAXParseException):
            msg = bozo_exception.getMessage()
            logger.warning(f"Error parsing {source_name}: {msg}")
        else:
            msg = str(bozo_exception)
            logger.error(f"Error parsing {source_name}: {msg}")

        logger.warning(f"Content: {truncate_content(source)}")

    return cast("list[ParserRSSEntry]", parsed.entries)


def _get_entry_text(entry: ParserRSSEntry) -> str:
    """
    Selects the first non-empty text from summary, description, content, or title.

    ``content`` is treated as a list of mappings and only the first item's
    ``value`` is used as a fallback.
    """
    text = str(entry.get("summary") or entry.get("description") or "")
    content = entry.get("content") or []
    first = next(iter(content), {})

    if not text and is_mapping(first):
        text = str(first.get("value") or "")

    if not text:
        text = str(entry.get("title") or "")

    return text


def resolve_date(entry: ParserRSSEntry, *keys: str) -> struct_time | None:
    """
    Resolves the first present date among ``keys`` to a struct_time.

    A parser may leave a ``*_parsed`` key present but ``None`` when it cannot read
    the feed's date format. The raw string that follows it is parsed by riko instead
    as a time-zone aware struct_time for datetimes or a naive struct_time for dates.
    A blank or unparseable value is skipped, with a warning for the latter, and the
    next key is tried.

    Args:

        entry: The parsed feed entry.
        keys: The entry keys to try, in order of preference.

    Returns:

        The resolved date, or ``None`` when no key carries a usable one.

    Examples:

        >>> entry = {"published_parsed": None, "published": "", "updated": "2020-06-15"}
        >>> resolve_date(entry, "published_parsed", "published", "updated")[:3]
        (2020, 6, 15)
        >>> resolve_date(entry, "published_parsed", "published") is None
        True

    """
    _date: struct_time | None = None

    for key in keys:
        value = entry.get(key) if key in entry else None

        if isinstance(value, (date, dt, struct_time)) or (
            isinstance(value, str) and value
        ):
            try:
                normalized = resolve_aware_datetime(value)
            except (ValueError, OverflowError):
                logger.warning(f"skipping unparseable {key} date {value!r}")
            else:
                is_date = isinstance(normalized, date)
                _date = date_to_tt(normalized) if is_date else normalized
                break

    return _date


def augment_entries(entries: Iterable[ParserRSSEntry]) -> Iterator[RSSEntry]:
    keys = ("published_parsed", "published")

    for raw in entries:
        pub_date = resolve_date(raw, *keys)
        updated_date = resolve_date(raw, "updated_parsed", "updated", *keys)
        text = _get_entry_text(raw)
        entry = cast("YahooRSSEntry", dict(raw))

        if not entry.get("summary"):
            cast("ExpandedRSSEntry", entry)["summary"] = text

        if not entry.get("description"):
            cast("ExpandedRSSEntry", entry)["description"] = text

        entry["author.name"] = entry.get("author_detail", {}).get("name")
        entry["author.uri"] = entry.get("author_detail", {}).get("href")
        entry["dc:creator"] = entry.get("author")
        entry["y:id"] = entry.get("id")
        entry["y:published"] = pub_date
        entry["y:title"] = entry.get("title")
        cast("ExpandedRSSEntry", entry)["updated_parsed"] = updated_date

        for key in ("published_parsed", "pubDate"):
            cast("ExpandedRSSEntry", entry)[key] = pub_date

        yield cast("RSSEntry", entry)
