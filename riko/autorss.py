# vim: sw=4:ts=4:expandtab
"""
riko.autorss
~~~~~~~~~~~~
Provides functions for finding RSS feeds from a site's LINK tags
"""

from collections.abc import Generator, Iterator
from io import StringIO, TextIOBase

import pygogo as gogo
from meza.compat import decode
from twisted.internet.defer import Deferred

from riko.bado import coroutine, microdom, return_value
from riko.bado.io import async_url_open
from riko.parsers import LinkParser
from riko.utils import Fetch

TIMEOUT = 10
logger = gogo.Gogo(__name__, monolog=True).logger


class RSSLinkParser(LinkParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, rss_only=True, **kwargs)


def file2entries(
    f: StringIO | Iterator[str] | TextIOBase, parser: RSSLinkParser
) -> Iterator[dict]:
    for line in f:
        parser.feed(decode(line))

        yield from parser.entry


def doc2entries(document) -> Iterator[dict]:
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


@coroutine  # pyright: ignore[reportArgumentType]
def async_get_rss(
    url: str, **kwargs
) -> Generator[Deferred[Iterator[dict]], Iterator[dict], None]:
    try:
        f = yield async_url_open(url, timeout=TIMEOUT)  # pyright: ignore[reportCallIssue]
    except ValueError:
        f = filter(None, url.splitlines())

    document = microdom.parse(f, lenient=True)
    return_value(doc2entries(document))


def get_rss(
    url: str, convert_charrefs=False, auto_sort=False, **kwargs
) -> Iterator[dict]:
    try:
        parser = RSSLinkParser(convert_charrefs=convert_charrefs, **kwargs)
    except TypeError:
        parser = RSSLinkParser(**kwargs)

    try:
        f = Fetch(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    entries = file2entries(f, parser)

    if auto_sort:
        entries = iter(sorted(entries, key=parser.keyfunc))

    return entries
