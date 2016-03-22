# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.lib.autorss
~~~~~~~~~~~~~~~~
Provides functions for tags from html
"""


from StringIO import StringIO
from HTMLParser import HTMLParser

from builtins import *


class LinkParser(HTMLParser):
    def reset(self):
        HTMLParser.reset(self)
        self.data = StringIO()

    def handle_data(self, data):
        self.data.write('%s\n' % data)


def get_text(html):
    parser = LinkParser()
    parser.feed(html)
    return parser.data.getvalue()
