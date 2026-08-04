# vim: sw=4:ts=4:expandtab
"""
riko._rssutils
~~~~~~~~~~
RSS/feed entry helpers: entry-text extraction, RSS enrichment, item generation,
and content truncation.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime as dt
from time import struct_time
from typing import cast, overload

from requests.structures import CaseInsensitiveDict

from riko.dates import ensure_tzinfo
from riko.types.general import Stream, StreamOrValueStream, ValueStream
from riko.types.values import BasicDict, ParserRSSEntry, RikoValue, RSSEntry


def _get_entry_text(entry: ParserRSSEntry) -> str:
    """
    Return the first non-empty text from summary, description, content, or title.

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
    for entry in entries:
        text = _get_entry_text(entry)
        pub_date = updated_date = None

        if not entry.get("summary"):
            entry["summary"] = text

        if not entry.get("description"):
            entry["description"] = text

        if "published_parsed" in entry:
            pub_date = updated_date = entry["published_parsed"]
        elif "published" in entry:
            pub_date = updated_date = entry["published"]

        if pub_date:
            pub_date = ensure_tzinfo(pub_date)

            if isinstance(pub_date, dt):
                pub_date = pub_date.timetuple()

        if "updated_parsed" in entry:
            updated_date = entry["updated_parsed"]
        elif "updated" in entry:
            updated_date = entry["updated"]

        if updated_date:
            updated_date = ensure_tzinfo(updated_date)

            if isinstance(updated_date, dt):
                updated_date = updated_date.timetuple()

        entry["author.name"] = entry.get("author_detail", {}).get("name")
        entry["author.uri"] = entry.get("author_detail", {}).get("href")
        entry["dc:creator"] = entry.get("author")
        entry["y:id"] = entry.get("id")
        entry["updated_parsed"] = updated_date
        entry["published_parsed"] = entry["y:published"] = entry["pubDate"] = pub_date
        entry["y:title"] = entry.get("title")
        yield cast(RSSEntry, entry)


@overload
def gen_items(content: RikoValue) -> ValueStream: ...  # noqa: E704
@overload  # noqa: E302
def gen_items(  # noqa: E704
    content: RikoValue, key: str, yield_if_none: bool = ...
) -> Stream: ...  # noqa: E704
@overload  # noqa: E302
def gen_items(  # noqa: E704
    content: RikoValue, key: None = ..., yield_if_none: bool = ...
) -> ValueStream: ...
def gen_items(  # noqa: E302
    content: RikoValue, key: str | None = None, yield_if_none=False
) -> StreamOrValueStream:
    if isinstance(content, (struct_time, dict, CaseInsensitiveDict)):
        yield {key: cast(BasicDict, content)} if key else content
    elif isinstance(content, (list, tuple)):
        for value in content:
            yield from gen_items(value, key)
    elif content is not None or yield_if_none:
        yield {key: content} if key else content


def truncate_content[T](content: T | object, length: int = 20) -> T:
    if isinstance(content, str):
        truncated = content[:length] + "…" if len(content) > length else content
    elif isinstance(content, (dict, CaseInsensitiveDict, Mapping)):
        truncated = {k: truncate_content(v) for k, v in content.items()}
    elif isinstance(content, (list, tuple, Sequence)):
        truncated = [truncate_content(v) for v in content]
    else:
        truncated = content

    return cast(T, truncated)
