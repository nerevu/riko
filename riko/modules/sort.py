# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.sort
~~~~~~~~~~~~~~~~~
Provides functions for sorting a stream by an item field.

Examples:
    basic usage::

        >>> from riko.modules.sort import pipe
        >>> items = [{'content': 'b'}, {'content': 'a'}, {'content': 'c'}]
        >>> next(pipe(items)) == {'content': 'a'}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from functools import reduce
from operator import itemgetter

from builtins import *

from . import operator
from riko.bado import itertools as ait

OPTS = {'listize': True, 'extract': 'rule'}
DEFAULTS = {'rule': {'sort_dir': 'asc', 'sort_key': 'content'}}
logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(stream, rule):
    reverse = rule.sort_dir == 'desc'
    return sorted(stream, key=itemgetter(rule.sort_key), reverse=reverse)


def async_parser(stream, rules, tuples, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        rules (List[obj]): the item independent rules (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        List(dict): Deferred output stream

    Examples:
        >>> from itertools import repeat
        >>> from riko.bado import react, _issync
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0] == {'content': 4})
        ...     kwargs = {'sort_key': 'content', 'sort_dir': 'desc'}
        ...     rule = Objectify(kwargs)
        ...     stream = ({'content': x} for x in range(5))
        ...     tuples = zip(stream, repeat(rule))
        ...     d = async_parser(stream, [rule], tuples, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> if _issync:
        ...     True
        ... else:
        ...     try:
        ...         react(run, _reactor=FakeReactor())
        ...     except SystemExit:
        ...         pass
        True
    """
    return ait.async_reduce(reducer, rules, stream)


def parser(stream, rules, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        rules (List[obj]): the item independent rules (Objectify instances).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        List(dict): The output stream

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {'sort_key': 'content', 'sort_dir': 'desc'}
        >>> rule = Objectify(kwargs)
        >>> stream = ({'content': x} for x in range(5))
        >>> tuples = zip(stream, repeat(rule))
        >>> parser(stream, [rule], tuples, **kwargs)[0] == {'content': 4}
        True
    """
    return reduce(reducer, rules, stream)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously and eagerly sorts the input source
    according to a specified key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
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
        Deferred: twisted.internet.defer.Deferred stream

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'rank': 'a'})
        ...     items = [{'rank': 'b'}, {'rank': 'a'}, {'rank': 'c'}]
        ...     d = async_pipe(items, conf={'rule': {'sort_key': 'rank'}})
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
    """An operator that eagerly sorts a stream according to a specified
    key. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
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
        dict: an item

    Examples:
        >>> items = [
        ...     {'rank': 'b', 'name': 'adam'},
        ...     {'rank': 'a', 'name': 'sue'},
        ...     {'rank': 'c', 'name': 'bill'}]
        >>> rule = {'sort_key': 'rank'}
        >>> next(pipe(items, conf={'rule': rule}))['rank'] == 'a'
        True
        >>> rule = {'sort_key': 'name'}
        >>> next(pipe(items, conf={'rule': rule}))['name'] == 'adam'
        True
        >>> rule = {'sort_key': 'name', 'sort_dir': 'desc'}
        >>> next(pipe(items, conf={'rule': rule}))['name'] == 'sue'
        True
    """
    return parser(*args, **kwargs)
