# vim: sw=4:ts=4:expandtab
"""
Provides functions for finding RSS feeds from a site's LINK tags.

Attributes:

    FEED_LINK_TYPES: The link types accepted as feeds by default, most preferred first.
    TIMEOUT: Seconds to wait for the page to load.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.base._config import settings
from riko.base._logging import get_logger
from riko.base._require_guards import normalize_strs
from riko.io._async import async_url_open
from riko.io._sync import Fetch, auto_close
from riko.parsing.documents import LinkParser
from riko.types._enums import FeedType

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from logging import Logger

    from riko.io._filelike import StringFileLike
    from riko.types._enums import FeedTypeLike, UserAgentLike
    from riko.types._streams import Stream

logger: Logger = get_logger(__name__)

FEED_LINK_TYPES: tuple[FeedType, ...] = tuple(FeedType)
TIMEOUT = settings.discovery_timeout


def _normalize_link_types(
    link_type: FeedTypeLike | Iterable[FeedTypeLike] | None,
) -> tuple[str, ...]:
    """Normalizes ``link_type`` into the accepted link types, in preference order."""
    types = FEED_LINK_TYPES if link_type is None else link_type
    errors = {"type_error": TypeError, "value_error": ValueError}

    if not (normalized := normalize_strs(types, "link_type", **errors)):
        raise ValueError("link_type must name at least one link type")

    return normalized


class RSSLinkParser(LinkParser):
    """
    Collects the feed links a page advertises in its ``LINK`` tags.

    Kwargs:

        link_type: The accepted link types, in preference order. ``keyfunc`` ranks links
            by this order (default: ``FEED_LINK_TYPES``).

        base_url: The URL that relative ``href`` values resolve against. Without it,
            links stay as written.

        strict: Whether only the ``type`` attribute decides a match. When False, an
            ``href`` ending in an accepted type also matches (default: True).

    Raises:

        ValueError: If ``link_type`` names no link type, or names one twice.
        TypeError: If ``link_type`` is not a string or iterable of strings.

    Examples:

        >>> parser = RSSLinkParser(base_url="https://example.com/news/")
        >>> parser.feed('<link type="application/atom+xml" href="/atom.xml">')
        >>> [entry["link"] for entry in parser.entry]
        ['https://example.com/atom.xml']

    """

    def __init__(
        self,
        *,
        link_type: FeedTypeLike | Iterable[FeedTypeLike] | None = None,
        base_url: str | None = None,
        strict: bool = True,
    ) -> None:
        normalized = _normalize_link_types(link_type)
        super().__init__(link_type=normalized, base_url=base_url, strict=strict)


def file2entries(f: StringFileLike | Iterator[str], parser: RSSLinkParser) -> Stream:
    # No parser.close(): a LINK tag is handled as soon as the line completing it is
    # fed, so nothing is pending at EOF. Only buffered text needs the flush that
    # get_text does.
    for line in f:
        parser.feed(line)

        for entry in parser.entry:
            yield dict(entry)


async def aload_rss_links(
    url: str,
    *,
    link_type: FeedTypeLike | Iterable[FeedTypeLike] | None = None,
    auto_sort: bool = False,
    user_agent: UserAgentLike | None = None,
    strict: bool = True,
) -> Stream:
    types = _normalize_link_types(link_type)

    try:
        f = await async_url_open(url, timeout=TIMEOUT, user_agent=user_agent)
    except ValueError:
        parser = RSSLinkParser(link_type=types, strict=strict)
        entries = file2entries(filter(None, url.splitlines()), parser)
    else:
        parser = RSSLinkParser(link_type=types, base_url=url, strict=strict)
        entries = auto_close(file2entries(f, parser), f)

    if auto_sort:
        entries = iter(sorted(entries, key=parser.keyfunc))

    return entries


def load_rss_links(
    url: str,
    *,
    link_type: FeedTypeLike | Iterable[FeedTypeLike] | None = None,
    auto_sort: bool = False,
    user_agent: UserAgentLike | None = None,
    strict: bool = True,
) -> Stream:
    types = _normalize_link_types(link_type)

    try:
        f = Fetch(url, timeout=TIMEOUT, user_agent=user_agent)
    except ValueError:
        parser = RSSLinkParser(link_type=types, strict=strict)
        entries = file2entries(filter(None, url.splitlines()), parser)
    else:
        parser = RSSLinkParser(link_type=types, base_url=url, strict=strict)
        entries = auto_close(file2entries(f, parser), f)

    if auto_sort:
        entries = iter(sorted(entries, key=parser.keyfunc))

    return entries
