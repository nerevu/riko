# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.lib.autorss
~~~~~~~~~~~~~~~~~~~
Provides functions for finding RSS feeds from a site's LINK tags
"""


from urllib2 import urlopen
from HTMLParser import HTMLParser
from itertools import chain, ifilter

from twisted.internet.defer import inlineCallbacks, returnValue

from pipe2py.twisted.utils import urlOpen

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

from pipe2py.lib.log import Logger
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
        f = ifilter(None, url.splitlines())

    returnValue(gen_entries(f, parser))


def get_rss(url):
    parser = LinkParser()

    try:
        f = urlopen(url, timeout=TIMEOUT)
    except ValueError:
        f = ifilter(None, url.splitlines())

    return gen_entries(f, parser)
