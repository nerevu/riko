# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.sum
~~~~~~~~~~~~~~~~
Provides functions for summing the items in a stream.

Examples:
    basic usage::

        >>> from riko.modules.sum import pipe
        >>> stream = pipe({'content': x} for x in range(5))
        >>> next(stream) == {'sum': Decimal('10')}
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
from decimal import Decimal
from builtins import *

from . import operator

OPTS = {}
DEFAULTS = {'sum_key': 'content', 'group_key': None}
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
        conf (dict): The pipe configuration.

    Returns:
        mixed: The output either a dict or iterable of dicts

    Examples:
        >>> from itertools import repeat
        >>> from riko.lib.utils import Objectify
        >>>
        >>> stream = ({'content': x} for x in range(5))
        >>> objconf = Objectify({'sum_key': 'content'})
        >>> tuples = zip(stream, repeat(objconf))
        >>> args = (stream, objconf, tuples)
        >>> parser(*args, assign='content') == {'content': Decimal('10')}
        True
        >>> objconf = Objectify({'sum_key': 'amount', 'group_key': 'x'})
        >>> stream = [
        ...     {'amount': 2, 'x': 'one'},
        ...     {'amount': 1, 'x': 'one'},
        ...     {'amount': 2, 'x': 'two'}]
        >>> tuples = zip(stream, repeat(objconf))
        >>> summed = parser(stream, objconf, tuples)
        >>> next(summed) == {'one': Decimal('3')}
        True
        >>> next(summed) == {'two': Decimal('2')}
        True
    """
    _sum = lambda group: sum(Decimal(g[objconf.sum_key]) for g in group)

    if objconf.group_key:
        keyfunc = itemgetter(objconf.group_key)
        sorted_stream = sorted(stream, key=keyfunc)
        grouped = it.groupby(sorted_stream, keyfunc)
        summed = ({key: _sum(group)} for key, group in grouped)
    else:
        summed = {kwargs['assign']: _sum(stream)}

    return summed


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """An aggregator that asynchronously and eagerly sums fields of items
    in a stream. Note that this pipe is not lazy if `group_key` is specified.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'assign' or
            'sum_key'.

            assign (str): Attribute to assign parsed content. If `sum_key` is
                set, this is ignored and the group keys are used instead.
                (default: content)

            sum_key (str): Item attribute to sum. (default: 'content').

            group_key (str): Item attribute to sum by. This will group items
                in the stream by the given key and report a sum for each
                group (default: None).

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the summed items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x) == {'sum': Decimal('10')})
        ...     items = ({'content': x} for x in range(5))
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
    """An aggregator that eagerly sums fields of items in a stream.
    Note that this pipe is not lazy if `group_key` is specified.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'assign',
            'sum_key', or 'group_key'.

            assign (str): Attribute to assign parsed content. If `sum_key` is
                set, this is ignored and the group keys are used instead.
                (default: content)

            sum_key (str): Item attribute to sum. (default: 'content').

            group_key (str): Item attribute to sum by. This will group items
                in the stream by the given key and report a sum for each
                group (default: None).

    Yields:
        dict: the summed items

    Examples:
        >>> stream = ({'content': x} for x in range(5))
        >>> next(pipe(stream)) == {'sum': Decimal('10')}
        True
        >>> stream = [
        ...     {'amount': 2, 'x': 'one'},
        ...     {'amount': 1, 'x': 'one'},
        ...     {'amount': 2, 'x': 'two'}]
        >>> summed = pipe(stream, conf={'sum_key': 'amount', 'group_key': 'x'})
        >>> next(summed) == {'one': Decimal('3')}
        True
        >>> next(summed) == {'two': Decimal('2')}
        True
    """
    return parser(*args, **kwargs)
