# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.typecast
~~~~~~~~~~~~~~~~~~~~~
Provides functions for casting fields into specific types.

Examples:
    basic usage::

        >>> from riko.modules.typecast import pipe
        >>>
        >>> conf = {'type': 'date'}
        >>> next(pipe({'content': '5/4/82'}, conf=conf))['typecast']['year']
        1982

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import
from . import processor
from riko.utils import cast

OPTS = {'field': 'content'}
DEFAULTS = {'type': 'text'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(content, objconf, skip=False, **kwargs):
    """ Parsers the pipe content

    Args:
        content (scalar): The content to cast
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: exchangerate)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': '1.0'}
        >>> objconf = Objectify({'type': 'int'})
        >>> kwargs = {'stream': item, 'assign': 'content'}
        >>> parser(item['content'], objconf, **kwargs)
        1
    """
    return kwargs['stream'] if skip else cast(content, objconf.type)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously parses a URL into its components.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'type'.
            type (str): The object type to cast to (default: text)

        assign (str): Attribute to assign parsed content (default: typecast)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['typecast'])
        ...     d = async_pipe({'content': '1.0'}, conf={'type': 'int'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that parses a URL into its components.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'type'.
            type (str): The object type to cast to (default: text)

        assign (str): Attribute to assign parsed content (default: typecast)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> from datetime import datetime as dt
        >>> next(pipe({'content': '1.0'}, conf={'type': 'int'}))['typecast']
        1
        >>> item = {'content': '5/4/82'}
        >>> conf = {'type': 'date'}
        >>> date = next(pipe(item, conf=conf, emit=True))['date']
        >>> date.isoformat() == '1982-05-04T00:00:00+00:00'
        True
        >>> item = {'content': dt(1982, 5, 4).timetuple()}
        >>> date = next(pipe(item, conf=conf, emit=True))['date']
        >>> date.isoformat() == '1982-05-04T00:00:00+00:00'
        True
        >>> item = {'content': 'False'}
        >>> conf = {'type': 'bool'}
        >>> next(pipe(item, conf=conf, emit=True))
        False
    """
    return parser(*args, **kwargs)
