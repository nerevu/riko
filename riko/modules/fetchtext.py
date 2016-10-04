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

from os.path import splitext
from contextlib import closing

from builtins import *
from six.moves.urllib.request import urlopen

from . import processor
from riko.lib import utils
from riko.bado import coroutine, return_value, io

OPTS = {'ftype': 'none', 'assign': 'content'}
DEFAULTS = {'encoding': 'utf-8'}
logger = gogo.Gogo(__name__, monolog=True).logger


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

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0][0]['content'])
        ...     url = get_path('lorem.txt')
        ...     objconf = Objectify({'url': url, 'encoding': 'utf-8'})
        ...     d = async_parser(None, objconf, False, assign='content')
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
        url = utils.get_abspath(objconf.url)
        f = yield io.async_url_open(url)
        assign = kwargs['assign']
        stream = [{assign: line.strip().decode(objconf.encoding)} for line in f]
        f.close()

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

    Returns:
        Tuple(Iter[dict], bool): Tuple of (stream, skip)

    Examples:
        >>> from riko import get_path
        >>> from riko.lib.utils import Objectify
        >>>
        >>> url = get_path('lorem.txt')
        >>> objconf = Objectify({'url': url, 'encoding': 'utf-8'})
        >>> result, skip = parser(None, objconf, False, assign='content')
        >>> result[0]['content'] == 'What is Lorem Ipsum?'
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        url = utils.get_abspath(objconf.url)

        with closing(urlopen(url)) as f:
            assign, encoding = kwargs['assign'], objconf.encoding
            stream = [{assign: line.strip().decode(encoding)} for line in f]

    return stream, skip


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
