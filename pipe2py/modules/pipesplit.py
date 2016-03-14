# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipesplit
~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for spliting a feed into identical copies

Use split when you want to perform different operations on data from the same
feed. The Union module is the reverse of Split, it merges multiple input feeds
into a single combined feed.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipesplit import pipe
        >>> pipe({'x': x} for x in xrange(5)).next()['feed'].next()
        {u'x': 0}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from itertools import imap
from copy import deepcopy

from . import operator
from pipe2py.lib.log import Logger

OPTS = {'extract': 'splits', 'ptype': 'int'}
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
        dict: A feed containing item

    Examples:
        >>> from itertools import repeat, izip
        >>>
        >>> conf = {'splits': 3}
        >>> kwargs = {'conf': conf}
        >>> feed = (({'x': x}) for x in xrange(5))
        >>> tuples = izip(feed, repeat(conf['splits']))
        >>> feeds = parser(feed, conf['splits'], tuples, **kwargs)
        >>> feeds.next()['feed']  # doctest: +ELLIPSIS
        <itertools.imap object at 0x...>
    """
    source = list(feed)
    # deepcopy each item passed along so that changes in one branch don't
    # affect the other branch
    for num in xrange(splits):
        title = 'feed %i of %i' % (num + 1, splits)
        yield {'title': title, 'feed': imap(deepcopy, source)}


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An operator that asynchronously and eagerly splits a feed into identical
    copies. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the key 'splits'.

            splits (int): the number of copies to create (default: 2).


    Returns:
        Deferred: twisted.internet.defer.Deferred feed of feeds

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print([f['feed'].next() for f in x])
        ...     d = asyncPipe({'x': x} for x in xrange(5))
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        [{u'x': 0}, {u'x': 0}]
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
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the key 'splits'.

            splits (int): the number of copies to create (default: 2).

    Yields:
        dict: a feed containing item

    Examples:
        >>> items = [{'x': x} for x in xrange(5)]
        >>> feeds = list(pipe(items))
        >>> [feed['feed'] for feed in feeds]  # doctest: +ELLIPSIS
        [<itertools.imap object at 0x...>, <itertools.imap object at 0x...>]
        >>> [feed['title'] for feed in feeds]
        [u'feed 1 of 2', u'feed 2 of 2']
        >>> feeds[0]['feed'].next()
        {u'x': 0}
        >>> len(list(pipe(items, conf={'splits': '3'})))
        3
    """
    return parser(*args, **kwargs)


