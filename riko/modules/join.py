# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.join
~~~~~~~~~~~~~~~~~
Provides functions for performing SQL like joins on separate sources.

Examples:
    basic usage::

        >>> from riko.modules.join import pipe
        >>>
        >>> items = ({'x': 'foo', 'sum': x} for x in range(5))
        >>> other = ({'x': 'foo', 'count': x + 5} for x in range(5))
        >>> joined = pipe(items, other=other)
        >>> next(joined) == {'x': 'foo', 'sum': 0, 'count': 5}
        True
        >>> len(list(joined))
        24


Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from itertools import product

from builtins import *  # noqa pylint: disable=unused-import
from meza.process import merge, join

from . import operator

# disable `dictize` since we do not need to access the configuration
OPTS = {'dictize': False}
DEFAULTS = {'join_key': None, 'lower': False}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, objconf, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf (obj): The pipe configuration (an Objectify instance)

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        other (Iter[dict]): stream to join

    Returns:
        Iter(dict): The output stream

    Examples:
        >>> from itertools import repeat
        >>> from meza.fntools import Objectify
        >>>
        >>> stream = ({'x': 'foo', 'sum': x} for x in range(5))
        >>> other = ({'x': 'foo', 'count': x + 5} for x in range(5))
        >>> objconf = Objectify({})
        >>> tuples = zip(stream, repeat(objconf))
        >>> joined = parser(stream, objconf, tuples, other=other)
        >>> next(joined) == {'x': 'foo', 'sum': 0, 'count': 5}
        True
        >>> len(list(joined))
        24
        >>> objconf = Objectify({'join_key': 'x', 'other_join_key': 'y'})
        >>> stream = ({'x': 'foo-%s' % x, 'sum': x} for x in range(5))
        >>> other = ({'y': 'foo-%s' % x, 'count': x + 5} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> joined = parser(stream, objconf, tuples, other=other)
        >>> next(joined) == {'count': 5, 'x': 'foo-0', 'sum': 0, 'y': 'foo-0'}
        True
        >>> len(list(joined))
        4
    """
    def compare(x, y):
        if objconf.lower:
            x_value, y_value = x.get(x_key, ''), y.get(y_key, '')
            equal = x_value.lower() == y_value.lower()
        else:
            equal = x.get(x_key) == y.get(y_key)

        return equal

    if objconf.join_key or objconf.other_join_key:
        x_key = objconf.join_key or objconf.other_join_key
        y_key = objconf.other_join_key or x_key
        prod = product(stream, kwargs['other'])

        joined = (
            merge([x, y]) for x, y in prod if compare(x, y))
    else:
        joined = join(stream, kwargs['other'])

    return joined


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously merges multiple source streams together.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'join_key' or
            'other_join_key'.
            join_key (str): Item attribute to join `items` on.
                (default: value of `other_join_key`).
            other_join_key (str): Item attribute to join `other` on.
                (default: value of `join_key`).
            lower (str): Transform values to lower case before comparing
                (for joining purposes, default: False)


        other (Iter[dict]): stream to join

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the merged streams

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     joined = {'x': 'foo', 'sum': 0, 'count': 5}
        ...     callback = lambda x: print(next(x) == joined)
        ...     items = ({'x': 'foo', 'sum': x} for x in range(5))
        ...     other = ({'x': 'foo', 'count': x + 5} for x in range(5))
        ...     d = async_pipe(items, conf={'join_key': 'x'}, other=other)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        True
    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """An operator that merges multiple streams together.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'join_key' or
            'other_join_key'.
            join_key (str): Item attribute to join `items` on.
                (default: value of `other_join_key`).
            other_join_key (str): Item attribute to join `other` on.
                (default: value of `join_key`).
            lower (str): Transform values to lower case before comparing
                (for joining purposes, default: False)

        other (Iter[dict]): stream to join

    Yields:
        dict: a merged stream item

    Examples:
        >>> items = [{'x': 'foo-%s' % x, 'sum': x} for x in range(5)]
        >>> other = ({'y': 'foo-%s' % x, 'count': x + 5} for x in range(5))
        >>> conf = {'join_key': 'x', 'other_join_key': 'y'}
        >>> joined = pipe(items, conf=conf, other=other)
        >>> next(joined) == {'count': 5, 'x': 'foo-0', 'sum': 0, 'y': 'foo-0'}
        True
        >>> next(joined) == {'count': 6, 'x': 'foo-1', 'sum': 1, 'y': 'foo-1'}
        True
        >>> other = ({'y': 'FOO-%s' % x, 'count': x + 5} for x in range(5))
        >>> conf = {'join_key': 'x', 'other_join_key': 'y', 'lower': True}
        >>> joined = pipe(items, conf=conf, other=other)
        >>> next(joined) == {'count': 5, 'x': 'foo-0', 'sum': 0, 'y': 'FOO-0'}
        True
        >>> next(joined) == {'count': 6, 'x': 'foo-1', 'sum': 1, 'y': 'FOO-1'}
        True
    """
    return parser(*args, **kwargs)
