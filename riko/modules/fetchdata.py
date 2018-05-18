# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.fetchdata
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching XML and JSON data sources.

Accesses and extracts data from XML and JSON data sources on the web. This data
can then be converted into an RSS feed or merged with other data in your Pipe.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchdata import pipe
        >>>
        >>> conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> next(pipe(conf=conf))['title'] == 'Business System Analyst'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from os import path as p

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.bado import coroutine, return_value, io
from riko.parsers import any2dict
from riko.utils import fetch, get_abspath

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
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0]['title'])
        ...     url = get_path('gigs.json')
        ...     objconf = Objectify({'url': url, 'path': 'value.items'})
        ...     d = async_parser(None, objconf, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Business System Analyst
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = get_abspath(objconf.url)
        ext = p.splitext(url)[1].lstrip('.')
        f = yield io.async_url_open(url)
        stream = any2dict(f, ext, objconf.html5, path=objconf.path)
        f.close()

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
        >>> url = get_path('gigs.json')
        >>> objconf = Objectify({'url': url, 'path': 'value.items'})
        >>> result = parser(None, objconf, stream={})
        >>> result[0]['title'] == 'Business System Analyst'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = get_abspath(objconf.url)
        ext = p.splitext(url)[1].lstrip('.')

        with fetch(**objconf) as f:
            ext = ext or f.ext
            stream = any2dict(f, ext, objconf.html5, path=objconf.path)

    return stream


@processor(isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'path' or 'html5'.

            url (str): The web site to fetch
            path (str): Dot separated path to extract (default: None, i.e.,
                return entire page)

            html5 (bool): Use the HTML5 parser (default: False)

    Returns:
        Deferred: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     path = 'value.items'
        ...     conf = {'url': get_path('gigs.json'), 'path': path}
        ...     d = async_pipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Business System Analyst
    """
    return async_parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'path' or 'html5'.

            url (str): The web site to fetch
            path (str): Dot separated path to extract (default: None, i.e.,
                return entire page)

            html5 (bool): Use the HTML5 parser (default: False)

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> next(pipe(conf=conf))['title'] == 'Business System Analyst'
        True
        >>> path = 'appointment'
        >>> conf = {'url': get_path('places.xml'), 'path': path}
        >>> next(pipe(conf=conf))['subject'] == 'Bring pizza home'
        True
        >>> conf = {'url': get_path('places.xml'), 'path': ''}
        >>> next(pipe(conf=conf))['reminder']
        '15'
        >>> conf = {'url': get_path('schools.xml'), 'path': 'data.row'}
        >>> next(pipe(conf=conf))['district_name'] == 'Turkana'
        True

    """
    return parser(*args, **kwargs)
