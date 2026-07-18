# vim: sw=4:ts=4:expandtab
"""
Provides functions for pushing items of a stream to a function using generator based
coroutines.

Examples:
    basic usage::

        >>> from riko.modules.receive import pipe as receiver
        >>> from riko.modules.send import pipe as sender
        >>> from riko.utils import noop
        >>>
        >>> target = receiver(conf={'name': 'receiver1', 'wait': 0.01, 'max_wait': 2}, func=noop)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({'x': x} for x in range(5))
        >>> source = sender(stream, others=['receiver1'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

"""

import pygogo as gogo

from riko import Objconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream
from riko.utils import send

from . import operator

OPTS: Opts = {"pollable": True, "emit": True}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(stream: Stream, objconf: Objconf, tuples: PipeTuples, **kwargs) -> Stream:
    """
    Parses the pipe content

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
        >>> target = receiver(conf={'name': 'receiver2', 'wait': 0.01, 'max_wait': 2}, func=noop)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> stream = ({'x': x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> source = parser(stream, None, tuples, others=['receiver2'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

    """
    others = kwargs["others"]
    ids = kwargs.get("ids")

    for item in stream:
        for target in others:
            target_id = send(target, item)

            if ids is not None and target_id is not None:
                ids[target] = target_id

        yield item


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    An operator that pushes items of a stream to a function using generator based
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
        >>> target = receiver(conf={'name': 'receiver3', 'wait': 0.01, 'max_wait': 2}, func=noop)
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> source = pipe([{'x': 0}], others=['receiver3'])
        >>> next(source)
        {'x': 0}
        >>> next(target)
        {'state': <StreamState.PENDING: 1>}
        >>> next(target)
        {'x': 0}

    """
    return parser(*args, **kwargs)
