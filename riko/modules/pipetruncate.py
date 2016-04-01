# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipetruncate
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for returning a specified number of items from a feed.

Contrast this with the Tail module, which also limits the number of feed items,
but returns items from the bottom of the feed.

Examples:
    basic usage::

        >>> from riko.modules.pipetruncate import pipe
        >>> items = ({'x': x} for x in range(5))
        >>> len(list(pipe(items, conf={'count': '4'})))
        4

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from itertools import islice

from builtins import *

from . import operator
from riko.lib.log import Logger

OPTS = {'ptype': 'int'}
DEFAULTS = {'start': 0}
logger = Logger(__name__).logger


def parser(feed, objconf, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf (obj): the item independent configuration (an Objectify
            instance).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source feed and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the `feed`
            iterator, so consuming it will consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Returns:
        Iter(dict): The output feed

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {'count': 4, 'start': 0}
        >>> objconf = Objectify(kwargs)
        >>> feed = ({'x': x} for x in range(5))
        >>> tuples = zip(feed, repeat(objconf))
        >>> len(list(parser(feed, objconf, tuples, **kwargs)))
        4
    """
    start = objconf.start
    stop = start + objconf.count
    return islice(feed, start, stop)


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously returns a specified number of items
    from a feed.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.
            May contain the key 'start'.

            count (int): desired feed length
            start (int): starting location (default: 0)

    Returns:
        Deferred: twisted.internet.defer.Deferred truncated feed

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(len(list(x)))
        ...     items = ({'x': x} for x in range(5))
        ...     d = asyncPipe(items, conf={'count': 4})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        4
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that returns a specified number of items from a feed.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.
            May contain the key 'start'.

            start (int): starting location (default: 0)
            count (int): desired feed length

    Yields:
        dict: a feed item

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> len(list(pipe(items, conf={'count': '4'})))
        4
        >>> feed = pipe(items, conf={'count': '2', 'start': '2'})
        >>> next(feed)
        {u'x': 2}
    """
    return parser(*args, **kwargs)
