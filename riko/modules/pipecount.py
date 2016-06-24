# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipecount
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for counting the number of items in a stream.

Examples:
    basic usage::

        >>> from riko.modules.pipecount import pipe
        >>> next(pipe({'x': x} for x in range(5))) == {'count': 5}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import operator
import pygogo as gogo

# disable `dictize` since we do not need to access the configuration
OPTS = {'dictize': False, 'ptype': 'none'}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, _, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        _ (None): Ignored.

        tuples (Iter[(dict, None)]): Iterable of tuples of (item, None)
            `item` is an element in the source. Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        dict: The output

    Examples:
        >>> from itertools import repeat
        >>>
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> parser(stream, None, tuples, assign='content') == {'content': 5}
        True
    """
    return {kwargs['assign']: len(list(stream))}


@operator(isasync=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously and eagerly counts the number of items
    in a stream. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'assign'.
            assign (str): Attribute to assign parsed content (default: count)

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the number of
            counted items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'count': 5})
        ...     items = ({'x': x} for x in range(5))
        ...     d = asyncPipe(items)
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


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An aggregator that eagerly counts the number of items in a stream.
    Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'assign'.
            assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: the number of counted items

    Examples:
        >>> items = ({'x': x} for x in range(5))
        >>> next(pipe(items))['count']
        5
    """
    return parser(*args, **kwargs)
