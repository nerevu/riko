# vim: sw=4:ts=4:expandtab
"""
Sums fields of the items in a stream.

Examples:
    Basic usage::

        >>> from riko.modules.sum import pipe
        >>>
        >>> stream = pipe({"content": x} for x in range(5))
        >>> next(stream)["sum"]
        Decimal('10')

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections.abc import Iterator
from decimal import Decimal
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._iterutils import group_by
from riko.types._configs import SumObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Stream
from riko.types._wrappers import PipeTuples

from . import operator

OPTS: Opts = Opts()
DEFAULTS: Defaults = {"sum_key": "content", "group_key": None}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    stream: Stream, objconf: SumObjconf, tuples: PipeTuples, **kwargs: object
) -> Decimal | Iterator[dict[str, Decimal]]:
    """
    Sums the ``sum_key`` field, optionally grouping by ``group_key``.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: the item independent configuration.

        tuples: Iterable of (item, objconf). `item` is an element in the source stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

    Returns:
        ``{value: sum}`` per group when ``group_key`` is given, otherwise the total
        sum

    Returns:
        - ``Iterator[{<group>: <sum>}]`` when ``group_key`` is set
        - ``<sum>`` when ``group_key`` is unset

    Examples:
        >>> from itertools import repeat
        >>> from meza.fntools import Objectify
        >>>
        >>> stream = ({"content": x} for x in range(5))
        >>> objconf = Objectify({"sum_key": "content"})
        >>> tuples = zip(stream, repeat(objconf))
        >>> parser(stream, objconf, tuples)
        Decimal('10')
        >>> objconf = Objectify({"sum_key": "amount", "group_key": "x"})
        >>> stream = [
        ...     {"amount": 2, "x": "one"},
        ...     {"amount": 1, "x": "one"},
        ...     {"amount": 2, "x": "two"},
        ... ]
        >>> tuples = zip(stream, repeat(objconf))
        >>> summed = parser(stream, objconf, tuples)
        >>> next(summed)
        {'one': Decimal('3')}
        >>> next(summed)
        {'two': Decimal('2')}

    """
    _sum = lambda group: sum(Decimal(g[objconf.sum_key]) for g in group) or Decimal(0)

    if objconf.group_key:
        grouped = group_by(stream, objconf.group_key)
        summed = ({key: _sum(group)} for key, group in grouped)
    else:
        summed = _sum(stream)

    return summed


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Decimal | Iterator[dict[str, Decimal]]:
    """
    Asynchronously sums fields of the items in a stream.

    Not lazy when ``group_key`` is set: grouping holds every item in memory.
    Without it the sum streams in constant memory, but still consumes the
    whole source before returning.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            sum_key (str): Field to sum (default: "content").

            group_key (str): Field to sum by. Groups items in the stream by
                the given key and reports a sum for each group (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the sum is assigned to. Ignored when ``group_key`` is set
            (the group keys are used instead) or ``emit`` is True (default: "sum").

        emit (bool): Whether to emit the sum directly rather than assign it. Ignored
            when ``group_key`` is set. Overrides ``assign`` (default: False).

    Yields:
        - ``{<group>: <sum>}`` when ``group_key`` is set
        - ``{<assign>: <sum>}`` when ``emit`` is False and ``group_key`` is unset
        - ``<sum>`` when ``emit`` is True and ``group_key`` is unset

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = ({"content": x} for x in range(5))
        ...     result = await async_pipe(items)
        ...     print(next(result)["sum"])
        >>>
        >>> run(main)
        10

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Decimal | Iterator[dict[str, Decimal]]:
    """
    Sums fields of the items in a stream.

    Not lazy when ``group_key`` is set: grouping holds every item in memory.
    Without it the sum streams in constant memory, but still consumes the
    whole source before returning.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            sum_key (str): Field to sum (default: "content").

            group_key (str): Field to sum by. Groups items in the stream by
                the given key and reports a sum for each group (default: None).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the sum is assigned to. Ignored when ``group_key`` is set
            (the group keys are used instead) or ``emit`` is True (default: "sum").

        emit (bool): Whether to emit the sum directly rather than assign it. Ignored
            when ``group_key`` is set. Overrides ``assign`` (default: False).

    Yields:
        - ``{<group>: <sum>}`` when ``group_key`` is set
        - ``{<assign>: <sum>}`` when ``emit`` is False and ``group_key`` is unset
        - ``<sum>`` when ``emit`` is True and ``group_key`` is unset

    Examples:
        >>> stream = ({"content": x} for x in range(5))
        >>> next(pipe(stream))["sum"]
        Decimal('10')
        >>> # Sum by group:
        >>> stream = [
        ...     {"amount": 2, "x": "one"},
        ...     {"amount": 1, "x": "one"},
        ...     {"amount": 2, "x": "two"},
        ... ]
        >>> summed = pipe(stream, conf={"sum_key": "amount", "group_key": "x"})
        >>> next(summed)
        {'one': Decimal('3')}
        >>> next(summed)
        {'two': Decimal('2')}

    """
    return parser(*args, **kwargs)
