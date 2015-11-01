# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.urlparse
~~~~~~~~~~~~~~~~~~~~~
Provides functions for parsing a URL into its six components.

Examples:
    basic usage::

        >>> from riko.modules.urlparse import pipe
        >>>
        >>> item = {'content': 'http://yahoo.com'}
        >>> scheme = {'component': 'scheme', 'content': 'http'}
        >>> next(pipe(item))['urlparse'][0] == scheme
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *
from six.moves.urllib.parse import urlparse
from . import processor

OPTS = {'ftype': 'text', 'field': 'content'}
DEFAULTS = {'parse_key': 'content'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(url, objconf, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        url (str): The link to parse
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> objconf = Objectify({'parse_key': 'value'})
        >>> result, skip = parser('http://yahoo.com', objconf, False)
        >>> next(result) == {'component': 'scheme', 'value': 'http'}
        True
    """
    if skip:
        stream = kwargs['stream']
    else:
        parsed = urlparse(url)
        items = parsed._asdict().items()
        stream = ({'component': k, objconf.parse_key: v} for k, v in items)

    return stream, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously parses a URL into its components.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: simplemath)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> scheme = {'component': 'scheme', 'content': 'http'}
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['urlparse'][0] == scheme)
        ...     d = async_pipe({'content': 'http://yahoo.com'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that parses a URL into its components.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'parse_key'.

            parse_key (str): Attribute to assign individual tokens (default:
                content)

        assign (str): Attribute to assign parsed content (default: hash)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> item = {'content': 'http://yahoo.com'}
        >>> scheme = {'component': 'scheme', 'content': 'http'}
        >>> next(pipe(item))['urlparse'][0] == scheme
        True
        >>> conf = {'parse_key': 'value'}
        >>> next(pipe(item, conf=conf, emit=True)) == {
        ...     'component': 'scheme', 'value': 'http'}
        True
    """
    return parser(*args, **kwargs)
