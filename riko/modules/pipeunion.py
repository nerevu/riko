# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipeunion
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for merging separate sources into a single feed of items.

Examples:
    basic usage::

        >>> from riko.modules.pipeunion import pipe
        >>> items = ({'x': x} for x in range(5))
        >>> other1 = ({'x': x + 5} for x in range(5))
        >>> other2 = ({'x': x + 10} for x in range(5))
        >>> len(list(pipe(items, others=[other1, other2])))
        15

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from itertools import chain

from builtins import *

from . import operator
from riko.lib.log import Logger
from riko.lib.utils import multiplex

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

    Kwargs:
        others (List[Iter(dict)]): List of feeds to join

    Returns:
        Iter(dict): The output feed

    Examples:
        >>> from itertools import repeat
        >>>
        >>> feed = ({'x': x} for x in range(5))
        >>> other1 = ({'x': x + 5} for x in range(5))
        >>> other2 = ({'x': x + 10} for x in range(5))
        >>> kwargs = {'others': [other1, other2]}
        >>> tuples = zip(feed, repeat(None))
        >>> len(list(parser(feed, None, tuples, **kwargs)))
        15
    """
    return chain(feed, multiplex(kwargs['others']))


@operator(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously merges multiple source feeds together.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        others (List[Iter(dict)]): List of feeds to join

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the merged feeds

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(len(list(x)))
        ...     items = ({'x': x} for x in range(5))
        ...     other1 = ({'x': x + 5} for x in range(5))
        ...     other2 = ({'x': x + 10} for x in range(5))
        ...     d = asyncPipe(items, others=[other1, other2])
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        15
    """
    return parser(*args, **kwargs)


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An operator that merges multiple feeds together.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        others (List[Iter(dict)]): List of feeds to join

    Yields:
        dict: a merged feed item

    Examples:
        >>> items = ({'x': x} for x in range(5))
        >>> other1 = ({'x': x + 5} for x in range(5))
        >>> other2 = ({'x': x + 10} for x in range(5))
        >>> len(list(pipe(items, others=[other1, other2])))
        15
    """
    return parser(*args, **kwargs)
