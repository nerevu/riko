# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipetail
~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for truncating a feed to the last N items.

Contrast this with the Truncate module, which limits the output to the first N
items.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipetail import pipe
        >>> items = ({'x': x} for x in xrange(5))
        >>> pipe(items, conf={'count': 2}).next()
        {u'x': 3}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from collections import deque

from . import operator
from pipe2py.lib.log import Logger

OPTS = {}
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
        List(dict): The output feed

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>> from itertools import repeat, izip
        >>>
        >>> kwargs = {'count': 2}
        >>> objconf = Objectify(kwargs)
        >>> feed = ({'x': x} for x in xrange(5))
        >>> tuples = izip(feed, repeat(objconf))
        >>> parser(feed, objconf, tuples, **kwargs)[0]
        {u'x': 3}
    """
    return deque(feed, int(objconf.count))


@operator(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously truncates a feed to the last N items.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.

            count (int): desired feed length

    Returns:
        Deferred: twisted.internet.defer.Deferred truncated feed

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next())
        ...     items = ({'x': x} for x in xrange(5))
        ...     d = asyncPipe(items, conf={'count': 2})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'x': 3}
    """
    return parser(*args, **kwargs)


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An operator that truncates a feed to the last N items.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'count'.

            count (int): desired feed length

    Yields:
        dict: a feed item

    Examples:
        >>> items = [{'x': x} for x in xrange(5)]
        >>> pipe(items, conf={'count': 2}).next()
        {u'x': 3}
    """
    return parser(*args, **kwargs)
