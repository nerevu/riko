# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.autorss
~~~~~~~~~~~~
Provides functions for finding RSS feeds from a site's LINK tags
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from itertools import chain
from html.parser import HTMLParser

from builtins import *  # noqa pylint: disable=unused-import
from meza.compat import decode
from riko.utils import fetch
from riko.bado import coroutine, return_value, microdom
from riko.bado.io import async_url_open

TIMEOUT = 10
logger = gogo.Gogo(__name__, monolog=True).logger


class LinkParser(HTMLParser):
    def reset(self):
        HTMLParser.reset(self)
        self.entry = iter([])

    def handle_starttag(self, tag, attrs):
        entry = dict(attrs)
        alternate = entry.get('rel') == 'alternate'
        rss = 'rss' in entry.get('type', '')

        if (alternate or rss) and 'href' in entry:
            entry['link'] = entry['href']
            entry['tag'] = tag
            self.entry = chain(self.entry, [entry])


def file2entries(f, parser):
    for line in f:
        parser.feed(decode(line))

        for entry in parser.entry:
            yield entry


def doc2entries(document):
    for node in document.childNodes:
        if hasattr(node, 'attributes') and node.attributes:
            entry = node.attributes
            alternate = entry.get('rel') == 'alternate'
            rss = 'rss' in entry.get('type', '')
        else:
            alternate = rss = None

        if (alternate or rss) and 'href' in entry:
            entry['link'] = entry['href']
            entry['tag'] = node.nodeName
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
        parser = LinkParser(convert_charrefs=convert_charrefs)
    except TypeError:
        parser = LinkParser()

    try:
        f = fetch(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    return file2entries(f, parser)
