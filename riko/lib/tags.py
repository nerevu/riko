# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.lib.tags
~~~~~~~~~~~~~
Provides functions for extracting tags from html
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from io import StringIO
from html.parser import HTMLParser

from builtins import *
from meza._compat import decode


class LinkParser(HTMLParser):
    def reset(self):
        HTMLParser.reset(self)
        self.data = StringIO()

    def handle_data(self, data):
        self.data.write('%s\n' % decode(data))


def get_text(html, convert_charrefs=False):
    try:
        parser = LinkParser(convert_charrefs=convert_charrefs)
    except TypeError:
        parser = LinkParser()

    try:
        parser.feed(html)
    except TypeError:
        parser.feed(decode(html))

    return parser.data.getvalue()
