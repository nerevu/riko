# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.fetch
~~~~~~~~~~~~~~~~~~
Provides functions for fetching RSS feeds.

Lets you specify an RSS news feed as input. This module understands feeds in
RSS, Atom, and RDF formats. Feeds contain one or more items.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetch import pipe
        >>>
        >>> url = get_path('feed.xml')
        >>> next(pipe(conf={'url': url}))['title'] == 'Donations'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.bado import coroutine, return_value, io
from riko.parsers import parse_rss
from riko.utils import gen_entries, get_abspath

OPTS = {'ftype': 'none'}
DEFAULTS = {'delay': 0}
logger = gogo.Gogo(__name__, monolog=True).logger
intersection = [
    'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']


@coroutine
def async_parser(_, objconf, skip=False, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Deferred: twisted.internet.defer.Deferred Iter[dict]

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     objconf = Objectify({'url': get_path('feed.xml'), 'delay': 0})
        ...     d = async_parser(None, objconf, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Donations
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = get_abspath(objconf.url)
        content = yield io.async_url_read(url, delay=objconf.delay)
        parsed = parse_rss(content)
        stream = gen_entries(parsed)

    return_value(stream)


def parser(_, objconf, skip=False, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        conf (dict): The pipe configuration

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'url': get_path('feed.xml'), 'delay': 0})
        >>> result = parser(None, objconf, stream={})
        >>> next(result)['title'] == 'Donations'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        parsed = parse_rss(**objconf)
        stream = gen_entries(parsed)

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches and parses a feed to return the
    entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.
            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.


    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> i = intersection
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(set(next(x).keys()).issuperset(i))
        ...     d = async_pipe(conf={'url': get_path('feed.xml')})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses a feed to return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'delay'.

            url (str): The web site to fetch.
            delay (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path('feed.xml')
        >>> keys = next(pipe(conf={'url': url})).keys()
        >>> set(keys).issuperset(intersection)
        True
        >>>
        >>> keys = next(pipe(conf={'url': url, 'memoize': True})).keys()
        >>> set(keys).issuperset(intersection)
        True
    """
    return parser(*args, **kwargs)
