# vim: sw=4:ts=4:expandtab
"""
Filters out non unique items from a stream according to a specified field.

Deduplication is windowed, not global: only the last ``limit`` values are remembered. A
duplicate that falls outside the window is yielded again. The sync pipe is lazy, and its
memory is bounded by ``limit``. The async pipe reads its whole source upfront.

Examples:

    Basic usage::

        >>> from riko.modules.uniq import pipe
        >>>
        >>> items = ({"x": x, "mod": x % 2} for x in range(5))
        >>> list(pipe(items, conf={"uniq_key": "mod"}))
        [{'x': 0, 'mod': 0}, {'x': 1, 'mod': 1}]

Attributes:

    OPTS: Operator decoration options.
    DEFAULTS: Default operator configuration.

"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from riko.base._logging import get_logger
from riko.types._options import DecorationOptions, Defaults

from ._decorators import operator

if TYPE_CHECKING:
    from logging import Logger

    from riko.coercion._configs import UniqObjconf
    from riko.types._streams import Stream
    from riko.types._wrappers import PipeTuples

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = DecorationOptions()
DEFAULTS: Defaults = {"uniq_key": "content", "limit": 1024}


def parser(
    stream: Stream, objconf: UniqObjconf, tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Filters the stream to items whose ``uniq_key`` value was not seen recently.

    Args:

        stream: The input stream. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The module configuration, containing `uniq_key` and `limit`.

        tuples: Iterable of (item, objconf). `item` is an element in the input stream.
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

    Not lazy: the whole source is read before the first item is yielded. An endless
    source never returns. Bound one with ``timeout`` instead.

    Args:

        items (Items): The input stream.

        conf (dict): The module configuration.

            uniq_key (str): Field which should be unique (default: "content").

            limit (int): Number of recently seen values to remember. A duplicate
                that falls outside this window is yielded again (default: 1024).

        context (Context): the run environment

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
        ...     result = async_pipe(items, conf={"uniq_key": "mod"})
        ...     print([i["mod"] async for i in result])
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

        items (Items): The input stream.

        conf (dict): The module configuration.

            uniq_key (str): Field which should be unique (default: "content").

            limit (int): Number of recently seen values to remember. A duplicate
                that falls outside this window is yielded again (default: 1024).

        context (Context): the run environment

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
