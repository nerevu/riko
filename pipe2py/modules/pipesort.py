# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipesort
~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for sorting a feed by an item field.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipesort import pipe
        >>> items = [{'title': 'b'}, {'title': 'a'}, {'title': 'c'}]
        >>> pipe(items).next()
        {u'title': u'a'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from operator import itemgetter

from . import operator
from pipe2py.lib.log import Logger
from pipe2py.twisted import utils as tu

OPTS = {'listize': True, 'extract': 'rule', 'parser': 'conf'}
DEFAULTS = {'sort_dir': 'asc', 'sort_key': 'title', 'rule': {}}
logger = Logger(__name__).logger


def reducer(feed, rule):
    reverse = rule.sort_dir == 'desc'
    return sorted(feed, key=itemgetter(rule.sort_key), reverse=reverse)


def asyncParser(feed, rules, tuples, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        keys (List[obj]): the item independent keys (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source feed and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the `feed`
            iterator, so consuming it will consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        conf (dict): The pipe configuration.

    Returns:
        List(dict): Deferred output feed

    Examples:
        >>> from itertools import repeat, izip
        >>> from twisted.internet.task import react
        >>> from pipe2py.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0])
        ...     kwargs = {'sort_key': 'title', 'sort_dir': 'desc'}
        ...     rule = Objectify(kwargs)
        ...     feed = ({'title': x} for x in xrange(5))
        ...     tuples = izip(feed, repeat(rule))
        ...     d = asyncParser(feed, [rule], tuples, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'title': 4}
    """
    return tu.asyncReduce(reducer, rules, feed)


def parser(feed, rules, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        keys (List[obj]): the item independent keys (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source feed and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the `feed`
            iterator, so consuming it will consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        conf (dict): The pipe configuration.

    Returns:
        List(dict): The output feed

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>> from itertools import repeat, izip
        >>>
        >>> kwargs = {'sort_key': 'title', 'sort_dir': 'desc'}
        >>> rule = Objectify(kwargs)
        >>> feed = ({'title': x} for x in xrange(5))
        >>> tuples = izip(feed, repeat(rule))
        >>> parser(feed, [rule], tuples, **kwargs)[0]
        {u'title': 4}
    """
    return reduce(reducer, rules, feed)


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously sorts the input source according to
    a specified key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the key 'rule'

            rule (dict): The sort configuration, can be either a dict or list
            of dicts. May contain the keys 'sort_key' or 'dir'.

                sort_key (str): Item attribute on which to sort by (default:
                    'title').

                sort_dir (str): The sort direction. Must be either 'asc' or 'desc'
                    (default: 'asc').

    Returns:
        Deferred: twisted.internet.defer.Deferred feed

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next())
        ...     items = [{'rank': 'b'}, {'rank': 'a'}, {'rank': 'c'}]
        ...     d = asyncPipe(items, conf={'rule': {'sort_key': 'rank'}})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'rank': u'a'}
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that sorts the input source according to a specified key.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the key 'rule'

            rule (dict): The sort configuration, can be either a dict or list
            of dicts. May contain the keys 'sort_key' or 'dir'.

                sort_key (str): Item attribute on which to sort by (default:
                    'title').

                sort_dir (str): The sort direction. Must be either 'asc' or 'desc'
                    (default: 'asc').

    Yields:
        dict: a feed item

    Examples:
        >>> items = [{'rank': 'b'}, {'rank': 'a'}, {'rank': 'c'}]
        >>> pipe(items, conf={'rule': {'sort_key': 'rank'}}).next()
        {u'rank': u'a'}
        >>> pipe(items, conf={'rule': {'sort_key': 'rank', 'sort_dir': 'desc'}}).next()
        {u'rank': u'c'}
    """
    return parser(*args, **kwargs)

