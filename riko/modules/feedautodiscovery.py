# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.feedautodiscovery
~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for finding the all available RSS and Atom feeds in a web
site.

Lets you enter a url and then examines those pages for information (like link
rel tags) about available feeds. If information about more than one feed is
found, then multiple items are returned. Because more than one feed can be
returned, the output from this module is often piped into a Fetch Feed module.

Also note that not all sites provide auto-discovery links on their web site's
home page. For a simpler alternative, try the Fetch Site Feed Module. It
returns the content from the first discovered feed.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.feedautodiscovery import pipe
        >>>
        >>> entry = next(pipe(conf={'url': get_path('bbc.html')}))
        >>> sorted(entry) == ['href', 'hreflang', 'link', 'rel', 'tag']
        True
        >>> entry['link'] == 'file://riko/data/greenhughes.xml'
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
from riko import autorss
from riko.utils import get_abspath
from riko.bado import coroutine, return_value


OPTS = {'ftype': 'none'}
logger = gogo.Gogo(__name__, monolog=True).logger


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

    Returns:
        Iter[dict]: Deferred stream

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['link'])
        ...     objconf = Objectify({'url': get_path('bbc.html')})
        ...     d = async_parser(None, objconf, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        file://riko/data/greenhughes.xml
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = get_abspath(objconf.url)
        stream = yield autorss.async_get_rss(url)

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

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'url': get_path('bbc.html')})
        >>> result = parser(None, objconf, stream={})
        >>> next(result)['link'] == 'file://riko/data/greenhughes.xml'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = get_abspath(objconf.url)
        stream = autorss.get_rss(url)

    return stream


@processor(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on a site.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper.

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['link'])
        ...     d = async_pipe(conf={'url': get_path('bbc.html')})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ...     pass
        ... except SystemExit:
        ...     pass
        ...
        file://riko/data/greenhughes.xml
    """
    return async_parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses the first feed found on a site.

    Args:
        item (dict): The entry to process (not used)
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'.

            url (str): The web site to fetch

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>> conf = {'url': get_path('bbc.html')}
        >>> next(pipe(conf=conf))['link'] == 'file://riko/data/greenhughes.xml'
        True
    """
    return parser(*args, **kwargs)
