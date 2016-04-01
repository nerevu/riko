# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipeuniq
~~~~~~~~~~~~~~~~~~~~~
Provides functions for filtering out non unique items from a feed according
to a specified field.

Removes duplicate items. You select the element to filter on, and Unique
removes the duplicates

Examples:
    basic usage::

        >>> from riko.modules.pipeuniq import pipe
        >>> items = ({'x': x, 'mod': x % 2} for x in range(5))
        >>> list(pipe(items, conf={'uniq_key': 'mod'})) == [
        ...     {u'x': 0, u'mod': 0}, {u'x': 1, u'mod': 1}]
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import operator
from riko.lib.log import Logger

OPTS = {'extract': 'uniq_key'}
DEFAULTS = {'uniq_key': 'content'}
logger = Logger(__name__).logger


def parser(feed, key, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        feed (Iter[dict]): The source feed. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        key (str): the field to extract.

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, rules)
            `item` is an element in the source feed (a DotDict instance)
            and `rules` is the rule configuration (an Objectify instance).
            Note: this shares the `feed` iterator, so consuming it will
            consume `feed` as well.

        kwargs (dict): Keyword arguments.

    Yields:
        dict: The output

    Examples:
        >>> from riko.lib.dotdict import DotDict
        >>> from itertools import repeat
        >>>
        >>> conf = {'uniq_key': 'mod'}
        >>> kwargs = {'conf': conf}
        >>> feed = (DotDict({'x': x, 'mod': x % 2}) for x in range(5))
        >>> tuples = zip(feed, repeat(conf['uniq_key']))
        >>> list(parser(feed, conf['uniq_key'], tuples, **kwargs)) == [
        ...     {u'x': 0, u'mod': 0}, {u'x': 1, u'mod': 1}]
        True

    """
    seen = set()

    for item in feed:
        value = item.get(key)

        if value not in seen:
            seen.add(value)
            yield item


@operator(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """An operator that asynchronously filters out non unique items according
    to a specified field.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'uniq_key'.

            uniq_key (str): Item attribute which should be unique (default:
                'content').

    Returns:
        Deferred: twisted.internet.defer.Deferred unique feed

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print([i['mod'] for i in x])
        ...     items = ({'x': x, 'mod': x % 2} for x in range(5))
        ...     d = asyncPipe(items, conf={'uniq_key': 'mod'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        [0, 1]
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that filters out non unique items according to a specified
    field.

    Args:
        items (Iter[dict]): The source feed.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'uniq_key'.

            uniq_key (str): Item attribute which should be unique (default:
                'content').

    Yields:
        dict: a feed item

    Examples:
        >>> items = [{'content': x, 'mod': x % 2} for x in range(5)]
        >>> list(pipe(items, conf={'uniq_key': 'mod'})) == [
        ...     {u'mod': 0, u'content': 0}, {u'mod': 1, u'content': 1}]
        True
        >>> feed = pipe(items)
        >>> next(feed) == {'mod': 0, 'content': 0}
        True
        >>> [item['content'] for item in feed]
        [1, 2, 3, 4]
    """
    return parser(*args, **kwargs)
