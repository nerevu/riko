# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.fetchtext
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching text data sources.

Accesses and extracts data from text sources on the web. This data can then be
merged with other data in your Pipe.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchtext import pipe
        >>>
        >>> conf = {'url': get_path('lorem.txt')}
        >>> next(pipe(conf=conf))['content'] == 'What is Lorem Ipsum?'
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
from riko import ENCODING
from riko.utils import fetch, auto_close, get_abspath
from riko.bado import coroutine, return_value, io

OPTS = {'ftype': 'none', 'assign': 'content'}
DEFAULTS = {'encoding': ENCODING}
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
        ...     callback = lambda x: print(next(x)['content'])
        ...     url = get_path('lorem.txt')
        ...     objconf = Objectify({'url': url, 'encoding': ENCODING})
        ...     d = async_parser(None, objconf, assign='content')
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        What is Lorem Ipsum?
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = get_abspath(objconf.url)
        f = yield io.async_url_open(url)
        assign = kwargs['assign']
        encoding = objconf.encoding
        _stream = ({assign: line.strip().decode(encoding)} for line in f)
        stream = auto_close(_stream, f)

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
        >>> url = get_path('lorem.txt')
        >>> objconf = Objectify({'url': url, 'encoding': ENCODING})
        >>> result = parser(None, objconf, assign='content')
        >>> next(result)['content'] == 'What is Lorem Ipsum?'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        f = fetch(decode=True, **objconf)
        _stream = ({kwargs['assign']: line.strip()} for line in f)
        stream = auto_close(_stream, f)

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'encoding'.

            url (str): The web site to fetch.
            encoding (str): The file encoding (default: utf-8).

        assign (str): Attribute to assign parsed content (default: content)


    Returns:
        Deferred: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['content'])
        ...     conf = {'url': get_path('lorem.txt')}
        ...     d = async_pipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        What is Lorem Ipsum?
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'encoding'.

            url (str): The web site to fetch
            encoding (str): The file encoding (default: utf-8).

        assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {'url': get_path('lorem.txt')}
        >>> next(pipe(conf=conf))['content'] == 'What is Lorem Ipsum?'
        True
    """
    return parser(*args, **kwargs)
