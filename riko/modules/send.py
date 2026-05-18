# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.send
~~~~~~~~~~~~~~~~~
Provides functions for pushing items of a stream to a function using generator based
coroutines.

Examples:
    basic usage::

        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.modules.send import pipe as sender
        >>> from riko.utils import noop
        >>>
        >>> target = receiver(conf={'name': 'receiver1'}, func=noop)
        >>> next(target)
        {'content': <Stream.PENDING: 1>}
        >>> stream = ({'x': x} for x in range(5))
        >>> source = sender(stream, others=['receiver1'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'content': <Stream.PENDING: 1>}
        >>> next(target)
        {'x': 0}
"""
from . import operator
from riko.utils import send

import pygogo as gogo

OPTS = {"emit": True, "pollable": True}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream, objconf, tuples, **kwargs):
    """Parses the pipe content

    Args:
        stream (Iter[dict]): The source. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf (obj): the item independent configuration (an Objectify
            instance).

        tuples (Iter[(dict, obj)]): Iterable of tuples of (item, objconf)
            `item` is an element in the source stream and `objconf` is the item
            configuration (an Objectify instance). Note: this shares the
            `stream` iterator, so consuming it will consume `stream` as well.

        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item
        others Iter[(str)]: Target names to receive each stream item.

    Returns:
        Iter(dict): The output stream

    Examples:
        >>> from itertools import repeat
        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.utils import noop
        >>>
        >>> target = receiver(conf={'name': 'receiver2'}, func=noop)
        >>> next(target)
        {'content': <Stream.PENDING: 1>}
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> source = parser(stream, None, tuples, others=['receiver2'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'content': <Stream.PENDING: 1>}
        >>> next(target)
        {'x': 0}
    """
    others = kwargs["others"]

    for item in stream:
        [send(target, item) for target in others]
        yield item


@operator(**OPTS)
def pipe(*args, **kwargs):
    """An operator that pushes items of a stream to a function using generator based
    coroutines.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        others Iter[(str)]: Target names to receive each stream item.
        conf (dict): The pipe configuration. May contain the key 'name'.

            name (str): The sender identifier

    Yields:
        dict: an item

    Examples:
        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.utils import noop
        >>>
        >>> target = receiver(conf={'name': 'receiver3'}, func=noop)
        >>> next(target)
        {'content': <Stream.PENDING: 1>}
        >>> source = pipe([{'x': 0}], others=['receiver3'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'content': <Stream.PENDING: 1>}
        >>> next(target)
        {'x': 0}
    """
    return parser(*args, **kwargs)
