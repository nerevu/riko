# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.count
~~~~~~~~~~~~~~~~~~
Provides functions for counting the number of items in a stream.

Examples:
    basic usage::

        >>> from riko.modules.count import pipe
        >>> next(pipe({'x': x} for x in range(5))) == {'count': 5}
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import itertools as it
import pygogo as gogo

from operator import itemgetter
from builtins import *

from . import operator

OPTS = {'extract': 'count_key'}
DEFAULTS = {'count_key': None}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, key, tuples, **kwargs):
    """ Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        key (str): the field to group by.

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments.

    Kwargs:
        conf (dict): The pipe configuration.

    Returns:
        mixed: The output either a dict or iterable of dicts

    Examples:
        >>> from itertools import repeat
        >>>
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> parser(stream, None, tuples, assign='content') == {'content': 5}
        True
        >>> conf = {'count_key': 'word'}
        >>> kwargs = {'conf': conf}
        >>> stream = [{'word': 'two'}, {'word': 'one'}, {'word': 'two'}]
        >>> tuples = zip(stream, repeat(conf['count_key']))
        >>> counted = parser(stream, conf['count_key'], tuples, **kwargs)
        >>> next(counted) == {'one': 1}
        True
        >>> next(counted) == {'two': 2}
        True
    """
    if key:
        keyfunc = itemgetter(key)
        sorted_stream = sorted(stream, key=keyfunc)
        grouped = it.groupby(sorted_stream, keyfunc)
        counted = ({key: len(list(group))} for key, group in grouped)
    else:
        counted = {kwargs['assign']: len(list(stream))}

    return counted


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously and eagerly counts the number of items
    in a stream. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'assign' or
            'count_key'.

            assign (str): Attribute to assign parsed content. If `count_key` is
                set, this is ignored and the group keys are used instead.
                (default: content)

            count_key (str): Item attribute to count by. This will group items
                in the stream by the given key and report a count for each
                group (default: None).


    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the number of
            counted items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'count': 5})
        ...     items = ({'x': x} for x in range(5))
        ...     d = async_pipe(items)
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
    """An aggregator that eagerly counts the number of items in a stream.
    Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the  keys 'assign' or
            'count_key'.

            assign (str): Attribute to assign parsed content. If `count_key` is
                set, this is ignored and the group keys are used instead.
                (default: content)

            count_key (str): Item attribute to count by. This will group items
                in the stream by the given key and report a count for each
                group (default: None).

    Yields:
        dict: the number of counted items

    Examples:
        >>> stream = ({'x': x} for x in range(5))
        >>> next(pipe(stream)) == {'count': 5}
        True
        >>> stream = [{'word': 'two'}, {'word': 'one'}, {'word': 'two'}]
        >>> counted = pipe(stream, conf={'count_key': 'word'})
        >>> next(counted) == {'one': 1}
        True
        >>> next(counted) == {'two': 2}
        True
    """
    return parser(*args, **kwargs)
