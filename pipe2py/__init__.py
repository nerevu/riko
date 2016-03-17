# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py
~~~~~~~
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from os import path as p

parts = [
    'feed.xml', 'blog.ouseful.info_feed.xml', 'gigs.json', 'places.xml',
    'www.bbc.co.uk_news.html', 'edition.cnn.html', 'google_spreadsheet.csv']


def get_url(name):
    return 'file://%s' % p.join('data', name)
