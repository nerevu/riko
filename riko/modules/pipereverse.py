# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipereverse
~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for flipping the order of all items in a feed.

Examples:
    basic usage::

        >>> from riko.modules.pipereverse import pipe
        >>> next(pipe({'x': x} for x in range(5)))
        {u'x': 4}

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
OPTS = {'dictize': False}
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
        >>> from itertools import repeat
        >>>
        >>> kwargs = {}
        >>> feed = ({'x': x} for x in range(5))
        >>> tuples = zip(feed, repeat(None))
        >>> next(parser(feed, None, tuples, **kwargs))
        {u'x': 4}
    """
    return reversed(list(feed))


@operator(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously reverses the order of source items in
    a feed. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

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
        {u'x': 4}
    """
    return parser(*args, **kwargs)


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An operator that eagerly reverses the order of source items in a feed.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Yields:
        dict: a feed item

    Examples:
        >>> items = ({'x': x} for x in range(5))
        >>> next(pipe(items))
        {u'x': 4}
    """
    return parser(*args, **kwargs)
