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


class Context(object):
    """The context of a pipeline
        verbose = debug printing during compilation and running
        describe_input = return pipe input requirements
        describe_dependencies = return a list of sub-pipelines used
        test = takes input values from default (skips the console prompt)
        inputs = a dictionary of values that overrides the defaults
            e.g. {'name one': 'test value1'}
    """
    def __init__(self, **kwargs):
        self.verbose = kwargs.get('verbose')
        self.test = kwargs.get('test')
        self.describe_input = kwargs.get('describe_input')
        self.describe_dependencies = kwargs.get('describe_dependencies')
        self.inputs = kwargs.get('inputs', {})
