# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipesplit
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for splitting a feed into identical copies

Use split when you want to perform different operations on data from the same
feed. The Union module is the reverse of Split, it merges multiple input feeds
into a single combined feed.

Examples:
    basic usage::

        >>> from riko.modules.pipesplit import pipe
        >>> feed1, feed2 = pipe({'x': x} for x in range(5))
        >>> next(feed1)
        {u'x': 0}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)


from copy import deepcopy

from builtins import *

from . import operator
from riko.lib.log import Logger

OPTS = {'extract': 'splits', 'ptype': 'int', 'objectify': False}
DEFAULTS = {'splits': 2}
logger = Logger(__name__).logger


def parser(feed, splits, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        splits (int): the number of copies to create.

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, splits)
            `item` is an element in the source feed (a DotDict instance)
            and `splits` is an int. Note: this shares the `feed` iterator,
            so consuming it will consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Yields:
        Iter(dict): a feed of items

    Examples:
        >>> from itertools import repeat
        >>>
        >>> conf = {'splits': 3}
        >>> kwargs = {'conf': conf}
        >>> feed = (({'x': x}) for x in range(5))
        >>> tuples = zip(feed, repeat(conf['splits']))
        >>> feeds = parser(feed, conf['splits'], tuples, **kwargs)
        >>> next(next(feeds))
        {u'x': 0}
    """
    source = list(feed)

    # deepcopy each item so that each split is independent
    for num in range(splits):
        yield map(deepcopy, source)


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An operator that asynchronously and eagerly splits a feed into identical
    copies. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'splits'.

            splits (int): the number of copies to create (default: 2).

    Returns:
        Deferred: twisted.internet.defer.Deferred iterable of feeds

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(next(x)))
        ...     d = asyncPipe({'x': x} for x in range(5))
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'x': 0}
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that eagerly splits a feed into identical copies.
    Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'splits'.

            splits (int): the number of copies to create (default: 2).

    Yields:
        Iter(dict): a feed of items

    Examples:
        >>> items = [{'x': x} for x in range(5)]
        >>> feed1, feed2 = pipe(items)
        >>> next(feed1)
        {u'x': 0}
        >>> len(list(pipe(items, conf={'splits': '3'})))
        3
    """
    return parser(*args, **kwargs)
