# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipesort
~~~~~~~~~~~~~~~~~~~~~
Provides functions for sorting a feed by an item field.

Examples:
    basic usage::

        >>> from riko.modules.pipesort import pipe
        >>> items = [{'content': 'b'}, {'content': 'a'}, {'content': 'c'}]
        >>> next(pipe(items))
        {u'content': u'a'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import reduce
from operator import itemgetter

from builtins import *

from . import operator
from riko.lib.log import Logger
from riko.twisted import utils as tu

OPTS = {'listize': True, 'extract': 'rule'}
DEFAULTS = {'rule': {'sort_dir': 'asc', 'sort_key': 'content'}}
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
        conf (dict): The pipe configuration.

    Returns:
        List(dict): Deferred output feed

    Examples:
        >>> from itertools import repeat
        >>> from twisted.internet.task import react
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0])
        ...     kwargs = {'sort_key': 'content', 'sort_dir': 'desc'}
        ...     rule = Objectify(kwargs)
        ...     feed = ({'content': x} for x in range(5))
        ...     tuples = zip(feed, repeat(rule))
        ...     d = asyncParser(feed, [rule], tuples, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': 4}
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
        conf (dict): The pipe configuration.

    Returns:
        List(dict): The output feed

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {'sort_key': 'content', 'sort_dir': 'desc'}
        >>> rule = Objectify(kwargs)
        >>> feed = ({'content': x} for x in range(5))
        >>> tuples = zip(feed, repeat(rule))
        >>> parser(feed, [rule], tuples, **kwargs)[0]
        {u'content': 4}
    """
    return reduce(reducer, rules, feed)


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An aggregator that asynchronously and eagerly sorts the input source
    according to a specified key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'rule'

            rule (dict): The sort configuration, can be either a dict or list
            of dicts. May contain the keys 'sort_key' or 'dir'.

                sort_key (str): Item attribute on which to sort by (default:
                    'content').

                sort_dir (str): The sort direction. Must be either 'asc' or
                    'desc' (default: 'asc').

    Returns:
        Deferred: twisted.internet.defer.Deferred feed

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
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
    """An operator that eagerly sorts a feed according to a specified
    key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'rule'

            rule (dict): The sort configuration, can be either a dict or list
                of dicts (default: {'sort_dir': 'asc', 'sort_key': 'content'}).
                Must contain the key 'sort_key'. May contain the key 'sort_dir'.

                sort_key (str): Item attribute on which to sort by.
                sort_dir (str): The sort direction. Must be either 'asc' or
                    'desc'.

    Yields:
        dict: a feed item

    Examples:
        >>> items = [
        ...     {'rank': 'b', 'name': 'adam'},
        ...     {'rank': 'a', 'name': 'sue'},
        ...     {'rank': 'c', 'name': 'bill'}]
        >>> next(pipe(items, conf={'rule': {'sort_key': 'rank'}}))['rank']
        u'a'
        >>> next(pipe(items, conf={'rule': {'sort_key': 'name'}}))['name']
        u'adam'
        >>> rule = {'sort_key': 'name', 'sort_dir': 'desc'}
        >>> next(pipe(items, conf={'rule': rule}))['name']
        u'sue'
    """
    return parser(*args, **kwargs)
