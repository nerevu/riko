# vim: sw=4:ts=4:expandtab
"""RSS/feed entry helpers for text extraction, enrichment, and content truncation."""

from __future__ import annotations

from datetime import date
from datetime import datetime as dt
from time import struct_time
from typing import TYPE_CHECKING, cast

import pygogo as gogo

from riko.coercion._dates import date_to_tt, normalize_tzinfo
from riko.types._guards import is_mapping

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from logging import Logger

    from riko.types._rss import (
        ExpandedRSSEntry,
        ParserRSSEntry,
        RSSEntry,
        YahooRSSEntry,
    )

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


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
                normalized = normalize_tzinfo(value)
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
