# vim: sw=4:ts=4:expandtab
"""
Provides functions for finding RSS feeds from a site's LINK tags
"""

from collections.abc import Iterator
from typing import cast

import pygogo as gogo

from riko.bado.io import async_url_open
from riko.parsers import LinkParser
from riko.types.general import Stream, StringFileTypes
from riko.utils import Fetch, auto_close

TIMEOUT = 10
logger = gogo.Gogo(__name__, monolog=True).logger


class RSSLinkParser(LinkParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, rss_only=True, **kwargs)


def file2entries(f: StringFileTypes | Iterator[str], parser: RSSLinkParser) -> Stream:
    for line in f:
        parser.feed(line)
        yield from parser.entry


def doc2entries(document) -> Stream:
    for node in document.childNodes:
        if hasattr(node, "attributes") and node.attributes:
            entry = node.attributes
            alternate = entry.get("rel") == "alternate"
            rss = "rss" in entry.get("type", "")
        else:
            alternate = rss = None
            entry = {}

        if (alternate or rss) and "href" in entry:
            entry["link"] = entry["href"]
            entry["tag"] = node.nodeName
            yield entry

    for node in document.childNodes:
        for entry in doc2entries(node):
            yield entry


async def async_get_rss(
    url: str, convert_charrefs=False, auto_sort=False, **kwargs
) -> Stream:
    try:
        parser = RSSLinkParser(convert_charrefs=convert_charrefs, **kwargs)
    except TypeError:
        parser = RSSLinkParser(**kwargs)

    try:
        f = await async_url_open(url, timeout=TIMEOUT)
    except ValueError:
        entries = file2entries(filter(None, url.splitlines()), parser)
    else:
        entries = auto_close(file2entries(f, parser), f)

    if auto_sort:
        entries = iter(sorted(entries, key=parser.keyfunc))

    return entries


def get_rss(url: str, convert_charrefs=False, auto_sort=False, **kwargs) -> Stream:
    try:
        parser = RSSLinkParser(convert_charrefs=convert_charrefs, **kwargs)
    except TypeError:
        parser = RSSLinkParser(**kwargs)

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
