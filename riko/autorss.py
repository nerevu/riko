# vim: sw=4:ts=4:expandtab
"""
Provides functions for finding RSS feeds from a site's LINK tags
"""

from collections.abc import Iterable, Iterator
from logging import Logger
from typing import TYPE_CHECKING, cast

import pygogo as gogo

from riko._io import Fetch, auto_close
from riko.bado.io import async_url_open
from riko.parsers import LinkParser
from riko.types._io import StringFileTypes
from riko.types._streams import Stream

if TYPE_CHECKING:
    from xml.dom.minidom import Node

TIMEOUT = 10
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


class RSSLinkParser(LinkParser):
    def __init__(
        self,
        *,
        link_type: str | Iterable[str] | None = None,
        **kwargs: bool,
    ) -> None:
        super().__init__(rss_only=True, link_type=link_type, **kwargs)


def file2entries(f: StringFileTypes | Iterator[str], parser: RSSLinkParser) -> Stream:
    for line in f:
        parser.feed(line)
        for entry in parser.entry:
            yield dict(entry)


def doc2entries(document: "Node") -> Iterator[object]:
    for node in document.childNodes:
        if hasattr(node, "attributes") and node.attributes:
            entry = node.attributes
            alternate = entry.get("rel") == "alternate"
            rss = "rss" in str(entry.get("type") or "")
        else:
            alternate = rss = None
            entry = {}

        if (alternate or rss) and "href" in entry:
            entry["link"] = entry["href"]
            entry["tag"] = node.nodeName or ""
            yield entry

    for node in document.childNodes:
        for entry in doc2entries(node):
            yield entry


async def async_get_rss(
    url: str,
    *,
    link_type: str | Iterable[str] | None = None,
    convert_charrefs: bool = False,
    auto_sort: bool = False,
    **kwargs: bool,
) -> Stream:
    try:
        parser = RSSLinkParser(
            convert_charrefs=convert_charrefs, link_type=link_type, **kwargs
        )
    except TypeError:
        parser = RSSLinkParser(link_type=link_type, **kwargs)

    try:
        f = await async_url_open(url, timeout=TIMEOUT)
    except ValueError:
        entries = file2entries(filter(None, url.splitlines()), parser)
    else:
        entries = auto_close(file2entries(f, parser), f)

    if auto_sort:
        entries = iter(sorted(entries, key=parser.keyfunc))

    return entries


def get_rss(
    url: str,
    *,
    link_type: str | Iterable[str] | None = None,
    convert_charrefs: bool = False,
    auto_sort: bool = False,
    **kwargs: bool,
) -> Stream:
    try:
        parser = RSSLinkParser(
            convert_charrefs=convert_charrefs, link_type=link_type, **kwargs
        )
    except TypeError:
        parser = RSSLinkParser(link_type=link_type, **kwargs)

    try:
        f = Fetch(url, timeout=TIMEOUT)
    except ValueError:
        entries = file2entries(filter(None, url.splitlines()), parser)
    else:
        stream = file2entries(cast(StringFileTypes, f), parser)
        entries = auto_close(stream, f)

    if auto_sort:
        entries = iter(sorted(entries, key=parser.keyfunc))

    return entries
