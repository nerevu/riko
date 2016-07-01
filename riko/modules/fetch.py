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

from builtins import *

from . import processor
from riko.lib import utils
from riko.bado import coroutine, return_value, io

OPTS = {'ftype': 'none'}
DEFAULTS = {'sleep': 0}
logger = gogo.Gogo(__name__, monolog=True).logger
intersection = [
    'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']


@coroutine
def async_parser(_, objconf, skip, **kwargs):
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
        Deferred: twisted.internet.defer.Deferred Tuple(Iter[dict], bool)

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['title'])
        ...     objconf = Objectify({'url': get_path('feed.xml'), 'sleep': 0})
        ...     d = async_parser(None, objconf, False, stream={})
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
        url = utils.get_abspath(objconf.url)
        content = yield io.async_url_read(url, delay=objconf.sleep)
        parsed = utils.parse_rss(content)
        stream = utils.gen_entries(parsed)

    result = (stream, skip)
    return_value(result)


def parser(_, objconf, skip, **kwargs):
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
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.lib.utils import Objectify
        >>>
        >>> objconf = Objectify({'url': get_path('feed.xml'), 'sleep': 0})
        >>> result, skip = parser(None, objconf, False, stream={})
        >>> next(result)['title'] == 'Donations'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)
        parsed = utils.parse_rss(url, objconf.sleep)
        stream = utils.gen_entries(parsed)

    return stream, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches and parses a feed to return the
    entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'sleep'.

            url (str): The web site to fetch.
            sleep (flt): Amount of time to sleep (in secs) before fetching the
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
            contain the key 'sleep'.

            url (str): The web site to fetch.
            sleep (flt): Amount of time to sleep (in secs) before fetching the
                url. Useful for simulating network latency. Default: 0.

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> keys = next(pipe(conf={'url': get_path('feed.xml')})).keys()
        >>> set(keys).issuperset(intersection)
        True
    """
    return parser(*args, **kwargs)
