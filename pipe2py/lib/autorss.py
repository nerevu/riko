# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.lib.autorss
~~~~~~~~~~~~~~~~~~~
Provides functions for finding RSS feeds from a site's LINK tags
"""


from urllib2 import urlopen
from HTMLParser import HTMLParser
from itertools import chain

from twisted.internet.defer import inlineCallbacks, returnValue

from pipe2py.twisted.utils import urlOpen

TIMEOUT = 10


class LinkParser(HTMLParser):
    def reset(self):
        HTMLParser.reset(self)
        self.href = []

    def handle_starttag(self, tag, attrs):
        keys = [('rel', 'alternate'), ('type', 'application/rss+xml')]

        if any(key in attrs for key in keys):
            self.href = chain(self.href, (e[1] for e in attrs if e[0] == 'href'))

from pipe2py.lib.log import Logger
logger = Logger(__name__).logger


@inlineCallbacks
def asyncGetRSS(url):
    # TODO: implement via an async parser, maybe get twisted.web.microdom.parse
    # working for HTML
    parser = LinkParser()

    try:
        f = yield urlOpen(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    # TODO: figure out how to stream the links as they are parsed
    for line in f:
        parser.feed(line)

    returnValue(parser.href)


def get_rss(url):
    parser = LinkParser()

    try:
        f = urlopen(url, timeout=TIMEOUT)
    except ValueError:
        f = filter(None, url.splitlines())

    for line in f:
        parser.feed(line)

        for href in parser.href:
            yield href

