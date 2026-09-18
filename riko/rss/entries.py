# vim: sw=4:ts=4:expandtab
"""RSS/feed entry helpers for text extraction, enrichment, and content truncation."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime as dt
from typing import TYPE_CHECKING, cast

from riko.coercion._dates import date_to_tt, normalize_tzinfo

if TYPE_CHECKING:
    from riko.types._rss import (
        ExpandedRSSEntry,
        ParserRSSEntry,
        RSSEntry,
        YahooRSSEntry,
    )


def _get_entry_text(entry: ParserRSSEntry) -> str:
    """
    Selects the first non-empty text from summary, description, content, or title.

    ``content`` is treated as a list of mappings and only the first item's
    ``value`` is used as a fallback.
    """
    text = str(entry.get("summary") or entry.get("description") or "")
    content = entry.get("content") or []
    first = next(iter(content), {})

    if not text and isinstance(first, Mapping):
        text = str(first.get("value") or "")

    if not text:
        text = str(entry.get("title") or "")

    return text


def augment_entries(entries: Iterable[ParserRSSEntry]) -> Iterator[RSSEntry]:
    for raw in entries:
        text = _get_entry_text(raw)
        entry = cast("YahooRSSEntry", dict(raw))
        pub_date = updated_date = None

        if not entry.get("summary"):
            cast("ExpandedRSSEntry", entry)["summary"] = text

        if not entry.get("description"):
            cast("ExpandedRSSEntry", entry)["description"] = text

        if "published_parsed" in entry:
            pub_date = updated_date = entry["published_parsed"]
        elif "published" in entry:
            pub_date = updated_date = entry["published"]

        if pub_date:
            pub_date = normalize_tzinfo(pub_date)

            if isinstance(pub_date, dt):
                pub_date = date_to_tt(pub_date)

        if "updated_parsed" in entry:
            updated_date = entry["updated_parsed"]
        elif "updated" in entry:
            updated_date = entry["updated"]

        if updated_date:
            updated_date = normalize_tzinfo(updated_date)

            if isinstance(updated_date, dt):
                updated_date = date_to_tt(updated_date)

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
