# vim: sw=4:ts=4:expandtab
"""
Provides functions for counting the number of items in a stream.

Examples:
    basic usage::

        >>> from riko.modules.count import pipe
        >>>
        >>> stream = [{'x': x} for x in range(5)]
        >>> next(pipe(stream))
        5
        >>> next(pipe(stream, emit=False))
        {'count': 5}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import itertools as it
from collections.abc import Iterator

import pygogo as gogo

from riko.types.general import Defaults, Opts, PipeTuples, Stream
from riko.utils import def_itemgetter

from . import operator

OPTS: Opts = {"extract": "count_key"}
DEFAULTS: Defaults = {"count_key": None}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, count_key: str, tuples: PipeTuples, **kwargs
) -> int | Iterator[dict[str, int]]:
    """
    Parses the pipe content

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
        >>> parser(stream, None, tuples)
        5
        >>> conf = {'count_key': 'word'}
        >>> kwargs = {'conf': conf}
        >>> stream = [{'word': 'two'}, {'word': 'one'}, {'word': 'two'}]
        >>> tuples = zip(stream, repeat(conf['count_key']))
        >>> counted = parser(stream, conf['count_key'], tuples, **kwargs)
        >>> next(counted)
        {'one': 1}
        >>> next(counted)
        {'two': 2}

    """
    if count_key:
        keyfunc = def_itemgetter(count_key)
        sorted_stream = sorted(stream, key=keyfunc)
        grouped = it.groupby(sorted_stream, keyfunc)
        counted = ({str(key): len(list(group))} for key, group in grouped)
    else:
        counted = len(list(stream))

    return counted


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """
    An operator that asynchronously and eagerly counts the number of items
    in a stream. Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'count_key'.

            count_key (str): Item attribute to count by. This will group items
                in the stream by the given key and report a count for each
                group (default: None).

        assign (str): Attribute to assign parsed content. If `count_key` is set,
            this is ignored and the group keys are used instead. (default:
            content)

    Returns:
        Deferred: twisted.internet.defer.Deferred iterator of the number of
            counted items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     items = ({'x': x} for x in range(5))
        ...     result = await async_pipe(items)
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        5

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> int | Iterator[dict[str, int]]:
    """
    An operator that eagerly counts the number of items in a stream.
    Note that this pipe is not lazy.

    Args:
        items (Iter[dict]): The source.
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'count_key'.

            count_key (str): Item attribute to count by. This will group items
                in the stream by the given key and report a count for each
                group (default: None).

        assign (str): Attribute to assign parsed content. If `count_key` is set,
            this is ignored and the group keys are used instead. (default:
            content)

    Yields:
        dict: the number of counted items

    Examples:
        >>> stream = [{'x': x} for x in range(5)]
        >>> next(pipe(stream))
        5
        >>> next(pipe(stream, emit=False))
        {'count': 5}
        >>> next(pipe(stream, emit=False, assign='content'))
        {'content': 5}
        >>> stream = [{'word': 'two'}, {'word': 'one'}, {'word': 'two'}]
        >>> counted = pipe(stream, conf={'count_key': 'word'})
        >>> next(counted)
        {'one': 1}
        >>> next(counted)
        {'two': 2}

    """
    return parser(*args, **kwargs)
