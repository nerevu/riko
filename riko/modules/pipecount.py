# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipecount
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for counting the number of items in a feed.

Examples:
    basic usage::

        >>> from riko.modules.pipecount import pipe
        >>> next(pipe({'x': x} for x in range(5)))
        {u'count': 5}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import operator
from riko.lib.log import Logger

# disable `dictize` since we do not need to access the configuration
OPTS = {'dictize': False, 'ptype': 'none'}
logger = Logger(__name__).logger


def parser(feed, _, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        _ (None): Ignored.

        tuples (Iter[(dict, None)]): Iterable of tuples of (item, None)
            `item` is an element in the source feed. Note: this shares the
            `feed` iterator, so consuming it will consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        dict: The output

    Examples:
        >>> from itertools import repeat
        >>>
        >>> feed = ({'x': x} for x in range(5))
        >>> tuples = zip(feed, repeat(None))
        >>> parser(feed, None, tuples, assign='content')
        {u'content': 5}
    """
    return {kwargs['assign']: len(list(feed))}


@operator(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously and eagerly counts the number of items
    in a feed. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'assign'.
            assign (str): Attribute to assign parsed content (default: count)

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the number of
            counted items

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     items = ({'x': x} for x in range(5))
        ...     d = asyncPipe(items)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'count': 5}
    """
    return parser(*args, **kwargs)


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An aggregator that eagerly counts the number of items in a feed.
    Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
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
