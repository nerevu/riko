# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.lib.autorss
~~~~~~~~~~~~~~~~
Provides functions for finding RSS feeds from a site's LINK tags
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from itertools import chain
from html.parser import HTMLParser

from builtins import *
from six.moves.urllib.request import urlopen
from twisted.internet.defer import inlineCallbacks, returnValue

from riko.twisted.utils import urlOpen

TIMEOUT = 10


class LinkParser(HTMLParser):
    def reset(self):
        HTMLParser.reset(self)
        self.entry = []

    def handle_starttag(self, tag, attrs):
        entry = dict(attrs)
        alternate = entry.get('rel') == 'alternate'
        rss = 'rss' in entry.get('type', '')

        if (alternate or rss) and 'href' in entry:
            entry['link'] = entry['href']
            entry['tag'] = tag
            self.entry = chain(self.entry, [entry])

from riko.lib.log import Logger
logger = Logger(__name__).logger


def gen_entries(f, parser):
    for line in f:
        parser.feed(line)

        for entry in parser.entry:
            yield entry


@inlineCallbacks
def asyncGetRSS(url):
    # TODO: implement via an async parser
    # maybe get twisted.web.microdom.parse working for HTML
    parser = LinkParser()

    try:
        f = yield urlOpen(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    returnValue(gen_entries(f, parser))


def get_rss(url):
    parser = LinkParser()

    try:
        f = urlopen(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    return gen_entries(f, parser)
