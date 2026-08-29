# vim: sw=4:ts=4:expandtab
"""
Performs SQL like joins on separate sources.

The ``other`` stream is retained so it can be matched against every source item,
so it cannot be unbounded. The source itself is consumed lazily and may be
unbounded. With a join key the comparison is a cartesian product, so cost grows
as ``len(items) * len(other)``.

Examples:
    Basic usage::

        >>> from riko.modules.join import pipe
        >>>
        >>> items = ({"x": "foo", "sum": x} for x in range(5))
        >>> other = ({"x": "foo", "count": x + 5} for x in range(5))
        >>> joined = pipe(items, other=other)
        >>> next(joined)
        {'x': 'foo', 'sum': 0, 'count': 5}
        >>> len(list(joined))
        24

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections.abc import Mapping
from logging import Logger
from typing import Any, cast

import pygogo as gogo
from meza.process import merge

from riko.dotdict import is_mapping
from riko.modules._prepare import require_arg
from riko.types._configs import JoinObjconf
from riko.types._options import Defaults, Opts
from riko.types._sentinels import MISSING
from riko.types._streams import Item, Items, Stream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = {"join_key": None, "lower": False}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream,
    objconf: JoinObjconf,
    tuples: PipeTuples,
    *,
    other: Items | None = None,
    **kwargs: object,
) -> Stream:
    """
    Joins the source against ``other`` by merging each matching pair.

    Falls back to a natural join when neither join key is set.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming it
            will consume `tuples` as well.

        objconf: The pipe configuration, containing `join_key`, `other_join_key`
            and `lower`.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

        other: The stream to join against. Required.

    Returns:
        Merged item matches.

    Raises:
        TypeError: If ``other`` is not given.

    Examples:
        >>> from itertools import repeat
        >>> from meza.fntools import Objectify
        >>>
        >>> stream = ({"x": "foo", "sum": x} for x in range(5))
        >>> other = ({"x": "foo", "count": x + 5} for x in range(5))
        >>> objconf = Objectify({})
        >>> tuples = zip(stream, repeat(objconf))
        >>> joined = parser(stream, objconf, tuples, other=other)
        >>> next(joined)
        {'x': 'foo', 'sum': 0, 'count': 5}
        >>> len(list(joined))
        24
        >>> objconf = Objectify({"join_key": "x", "other_join_key": "y"})
        >>> stream = ({"x": f"foo-{x}", "sum": x} for x in range(5))
        >>> other = ({"y": f"foo-{x}", "count": x + 5} for x in range(5))
        >>> tuples = zip(stream, repeat(objconf))
        >>> joined = parser(stream, objconf, tuples, other=other)
        >>> next(joined)
        {'x': 'foo-0', 'sum': 0, 'y': 'foo-0', 'count': 5}
        >>> len(list(joined))
        4

    """
    other = require_arg(other, "other", "join", strict=True)

    def compare(x: Item, y: Item, x_key: str, y_key: str) -> bool:
        if isinstance(x, Mapping) and isinstance(y, Mapping):
            x_value, y_value = x.get(x_key, MISSING), y.get(y_key, MISSING)

            if x_value is MISSING or y_value is MISSING:
                equal = False
            elif (
                objconf.lower and isinstance(x_value, str) and isinstance(y_value, str)
            ):
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
        others = list(other)
        joined = (
            merge([x, y])
            for x in stream
            for y in others
            if compare(x, y, x_key=x_key, y_key=y_key)
        )
    else:
        others = list(filter(is_mapping, other))
        joined = (merge([x, y]) for x in stream for y in others)

    return cast(Stream, joined)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously joins a source stream against another stream.

    ``other`` is retained and replayed against every source item, so it cannot be
    unbounded. The source stream is consumed lazily.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            join_key (str): Field to join ``items`` on (default: the value of
                ``other_join_key``).

            other_join_key (str): Field to join ``other`` on (default: the value
                of ``join_key``).

            lower (bool): Whether to compare string values case-insensitively
                (default: False).

        context (Context): the execution context

    Kwargs:
        other (Items): The stream to join against. Required.

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "join").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - merged ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Notes:
        A natural join is used when neither join key is set. Items missing the
        join field never match.

    Raises:
        TypeError: If ``other`` is not given.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = ({"x": "foo", "sum": x} for x in range(5))
        ...     other = ({"x": "foo", "count": x + 5} for x in range(5))
        ...     result = await async_pipe(items, conf={"join_key": "x"}, other=other)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'x': 'foo', 'sum': 0, 'count': 5}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Joins a source stream against another stream.

    ``other`` is retained and replayed against every source item, so it cannot be
    unbounded. The source stream is consumed lazily.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            join_key (str): Field to join ``items`` on (default: the value of
                ``other_join_key``).

            other_join_key (str): Field to join ``other`` on (default: the value
                of ``join_key``).

            lower (bool): Whether to compare string values case-insensitively
                (default: False).

        context (Context): the execution context

    Kwargs:
        other (Items): The stream to join against. Required.

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "join").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - merged ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Notes:
        A natural join is used when neither join key is set. Items missing the
        join field never match.

    Raises:
        TypeError: If ``other`` is not given.

    Examples:
        >>> items = [{"x": f"foo-{x}", "sum": x} for x in range(5)]
        >>> other = ({"y": f"foo-{x}", "count": x + 5} for x in range(5))
        >>> conf = {"join_key": "x", "other_join_key": "y"}
        >>> joined = pipe(items, conf=conf, other=other)
        >>> next(joined)
        {'x': 'foo-0', 'sum': 0, 'y': 'foo-0', 'count': 5}
        >>> next(joined)
        {'x': 'foo-1', 'sum': 1, 'y': 'foo-1', 'count': 6}
        >>> other = ({"y": f"FOO-{x}", "count": x + 5} for x in range(5))
        >>> conf = {"join_key": "x", "other_join_key": "y", "lower": True}
        >>> joined = pipe(items, conf=conf, other=other)
        >>> next(joined)
        {'x': 'foo-0', 'sum': 0, 'y': 'FOO-0', 'count': 5}
        >>> next(joined)
        {'x': 'foo-1', 'sum': 1, 'y': 'FOO-1', 'count': 6}
        >>> items = [{"x": "foo", "sum": 0}, {"sum": 1}]
        >>> other = [{"y": "foo", "count": 5}, {"count": 6}]
        >>> conf = {"join_key": "x", "other_join_key": "y"}
        >>> [i["sum"] for i in pipe(items, conf=conf, other=other)]
        [0]

    """
    return parser(*args, **kwargs)
