# vim: sw=4:ts=4:expandtab
"""
Provides functions for performing SQL like joins on separate sources.

Examples:
    basic usage::

        >>> from riko.modules.join import pipe
        >>>
        >>> items = ({'x': 'foo', 'sum': x} for x in range(5))
        >>> other = ({'x': 'foo', 'count': x + 5} for x in range(5))
        >>> joined = pipe(items, other=other)
        >>> next(joined)
        {'x': 'foo', 'sum': 0, 'count': 5}
        >>> len(list(joined))
        24


Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Generator, Iterator, Mapping
from itertools import product
from typing import cast

import pygogo as gogo
from meza.process import join, merge

from riko import Objconf
from riko.dotdict import is_mapping
from riko.types.general import Defaults, ItemArg, Opts, PipeTuples, Stream
from riko.types.values import ComplexMapping

from . import operator

OPTS = Opts()
DEFAULTS: Defaults = {"join_key": None, "lower": False}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: Objconf, tuples: PipeTuples, **kwargs
) -> Iterator[ComplexMapping]:
    """
    Parses the pipe content

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
        >>> next(joined)
        {'x': 'foo', 'sum': 0, 'count': 5}
        >>> len(list(joined))
        24
        >>> objconf = Objectify({'join_key': 'x', 'other_join_key': 'y'})
        >>> stream = ({'x': f'foo-{x}', 'sum': x} for x in range(5))
        >>> other = ({'y': f'foo-{x}', 'count': x + 5} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> joined = parser(stream, objconf, tuples, other=other)
        >>> next(joined)
        {'x': 'foo-0', 'sum': 0, 'y': 'foo-0', 'count': 5}
        >>> len(list(joined))
        4

    """
    other = cast(Stream, kwargs["other"])

    def compare(x: ItemArg, y: ItemArg, x_key: str, y_key: str) -> bool:
        if isinstance(x, Mapping) and isinstance(y, Mapping):
            x_value, y_value = x.get(x_key, ""), y.get(y_key, "")

            if objconf.lower and isinstance(x_value, str) and isinstance(y_value, str):
                equal = x_value.lower() == y_value.lower()
            else:
                equal = x_value == y_value
        else:
            logger.warning(f"Unsupported types for compare: {type(x)} and {type(y)}")
            equal = False

        return equal

    if objconf.join_key or objconf.other_join_key:
        x_key = objconf.join_key or objconf.other_join_key
        y_key = objconf.other_join_key or x_key
        prod = product(stream, other)
        _joined = (
            merge([cast(ComplexMapping, x), cast(ComplexMapping, y)])
            for x, y in prod
            if compare(x, y, x_key=x_key, y_key=y_key)
        )
        joined = cast(Generator[ComplexMapping, None, None], _joined)
    else:
        joined = join(filter(is_mapping, stream), filter(is_mapping, other))

    return joined


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Iterator[ComplexMapping]:
    """
    An operator that asynchronously merges multiple source streams together.

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
        >>> async def run(reactor):
        ...     items = ({'x': 'foo', 'sum': x} for x in range(5))
        ...     other = ({'x': 'foo', 'count': x + 5} for x in range(5))
        ...     result = await async_pipe(items, conf={'join_key': 'x'}, other=other)
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {'x': 'foo', 'sum': 0, 'count': 5}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[ComplexMapping]:
    """
    An operator that merges multiple streams together.

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
        >>> items = [{'x': f'foo-{x}', 'sum': x} for x in range(5)]
        >>> other = ({'y': f'foo-{x}', 'count': x + 5} for x in range(5))
        >>> conf = {'join_key': 'x', 'other_join_key': 'y'}
        >>> joined = pipe(items, conf=conf, other=other)
        >>> next(joined)
        {'x': 'foo-0', 'sum': 0, 'y': 'foo-0', 'count': 5}
        >>> next(joined)
        {'x': 'foo-1', 'sum': 1, 'y': 'foo-1', 'count': 6}
        >>> other = ({'y': f'FOO-{x}', 'count': x + 5} for x in range(5))
        >>> conf = {'join_key': 'x', 'other_join_key': 'y', 'lower': True}
        >>> joined = pipe(items, conf=conf, other=other)
        >>> next(joined)
        {'x': 'foo-0', 'sum': 0, 'y': 'FOO-0', 'count': 5}
        >>> next(joined)
        {'x': 'foo-1', 'sum': 1, 'y': 'FOO-1', 'count': 6}

    """
    return parser(*args, **kwargs)
