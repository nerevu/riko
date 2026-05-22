# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.autorss
~~~~~~~~~~~~
Provides functions for finding RSS feeds from a site's LINK tags
"""
import pygogo as gogo

from meza.compat import decode
from riko.parsers import LinkParser
from riko.utils import fetch
from riko.bado import coroutine, return_value, microdom
from riko.bado.io import async_url_open

TIMEOUT = 10
logger = gogo.Gogo(__name__, monolog=True).logger


class RSSLinkParser(LinkParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, rss_only=True, **kwargs)


def file2entries(f, parser):
    for line in f:
        parser.feed(decode(line))

        for entry in parser.entry:
            yield entry


def doc2entries(document):
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


@coroutine
def async_get_rss(url, convert_charrefs=False):
    try:
        f = yield async_url_open(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    document = microdom.parse(f, lenient=True)
    return_value(doc2entries(document))


def get_rss(url, convert_charrefs=False):
    try:
        parser = RSSLinkParser(convert_charrefs=convert_charrefs)
    except TypeError:
        parser = RSSLinkParser()

    try:
        f = fetch(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    return file2entries(f, parser)
