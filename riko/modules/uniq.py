# vim: sw=4:ts=4:expandtab
"""
Filters out non unique items from a stream according to a specified field.

Deduplication is windowed, not global: only the last ``limit`` values are
remembered, so a duplicate that falls outside the window is yielded again.
Lazy, and memory is bounded by ``limit``.

Examples:
    Basic usage::

        >>> from riko.modules.uniq import pipe
        >>>
        >>> items = ({"x": x, "mod": x % 2} for x in range(5))
        >>> list(pipe(items, conf={"uniq_key": "mod"}))
        [{'x': 0, 'mod': 0}, {'x': 1, 'mod': 1}]

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections import deque
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.types.configs import UniqObjconf
from riko.types.general import Defaults, Opts, PipeTuples, Stream

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = {"uniq_key": "content", "limit": 1024}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: UniqObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Yields items whose ``uniq_key`` value has not been seen recently.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The pipe configuration, containing `uniq_key` and `limit`.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

    Yields:
        Each item whose ``uniq_key`` value is not among the last ``limit`` seen.

    Examples:
        >>> from itertools import repeat
        >>> from meza.fntools import Objectify
        >>>
        >>> conf = {"uniq_key": "mod", "limit": 256}
        >>> objconf = Objectify(conf)
        >>> kwargs = {"conf": conf}
        >>> stream = ({"x": x, "mod": x % 2} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> list(parser(stream, objconf, tuples, **kwargs))
        [{'x': 0, 'mod': 0}, {'x': 1, 'mod': 1}]

    """
    seen = deque(maxlen=objconf.limit)

    for item in stream:
        value = item.get(objconf.uniq_key)

        if value not in seen:
            seen.append(value)
            yield item


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously filters out non unique items according to a specified field.

    Lazy: items stream through and memory is bounded by ``limit``.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            uniq_key (str): Field which should be unique (default: "content").

            limit (int): Number of recently seen values to remember. A duplicate
                that falls outside this window is yielded again (default: 1024).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "uniq").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = ({"x": x, "mod": x % 2} for x in range(5))
        ...     result = await async_pipe(items, conf={"uniq_key": "mod"})
        ...     print([i["mod"] for i in result])
        >>>
        >>> run(main)
        [0, 1]

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Filters out non unique items according to a specified field.

    Lazy: items stream through and memory is bounded by ``limit``.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            uniq_key (str): Field which should be unique (default: "content").

            limit (int): Number of recently seen values to remember. A duplicate
                that falls outside this window is yielded again (default: 1024).

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "uniq").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> items = [{"content": x, "mod": x % 2} for x in range(5)]
        >>> list(pipe(items, conf={"uniq_key": "mod"}))
        [{'content': 0, 'mod': 0}, {'content': 1, 'mod': 1}]
        >>> stream = pipe(items)
        >>> next(stream)
        {'content': 0, 'mod': 0}
        >>> [item["content"] for item in stream]
        [1, 2, 3, 4]

    """
    return parser(*args, **kwargs)
