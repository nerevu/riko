# vim: sw=4:ts=4:expandtab
"""
Sorts a stream by one or more item fields.

Not lazy: ranking needs every item, so the source is materialized and cannot be
unbounded.

Examples:
    Basic usage::

        >>> from riko.modules.sort import pipe
        >>>
        >>> items = [{"content": "b"}, {"content": "a"}, {"content": "c"}]
        >>> next(pipe(items))
        {'content': 'a'}

Attributes:
    OPTS: Operator wrapper options.
    DEFAULTS: Default operator configuration.

"""

from collections.abc import Sequence
from functools import reduce
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._iterutils import def_itemgetter
from riko.bado.itertools import async_reduce
from riko.cast import SortableCastType
from riko.types._options import Defaults, Opts
from riko.types._streams import Stream
from riko.types._wrappers import PipeTuples
from riko.types.modules import SortConfRule

from . import operator

OPTS: Opts = {"listize": True, "extract": "rule"}
sort_type = SortableCastType.TEXT
DEFAULTS: Defaults = {"rule": SortConfRule(dir="asc", field="content", type=sort_type)}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(stream: Stream, rule: SortConfRule) -> Stream:
    reverse = rule.dir.lower() == "desc" if rule.dir else False
    keyfunc = def_itemgetter(rule.field, type_=rule.type)
    return iter(sorted(stream, key=keyfunc, reverse=reverse))


async def async_parser(
    stream: Stream, rules: Sequence[SortConfRule], tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Asynchronously sorts the stream by each rule.

    Rules are applied in reverse so the first rule is the primary key.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        rules: The item independent sort rules.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:
        The fully sorted stream.

    Examples:
        >>> from itertools import repeat
        >>> from riko import run, issync
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     kwargs = {"field": "content", "dir": "desc"}
        ...     rule = Objectify(kwargs)
        ...     stream = ({"content": result} for result in range(5))
        ...     tuples = zip(stream, repeat(rule))
        ...     result = await async_parser(stream, [rule], tuples, **kwargs)
        ...     print(next(result))
        >>>
        >>> if issync:
        ...     {"content": 4}
        ... else:
        ...     run(main)
        {'content': 4}

    """
    return await async_reduce(reducer, list(reversed(rules)), stream)


def parser(
    stream: Stream, rules: Sequence[SortConfRule], tuples: PipeTuples, **kwargs: object
) -> Stream:
    """
    Sorts the stream by each rule.

    Rules are applied in reverse so the first rule is the primary key.

    Args:
        stream: The source. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        rules: The item independent sort rules.

        tuples: Iterable of tuples of (item, objconf) `item` is an element in the
            source stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:
        The fully sorted stream.

    Examples:
        >>> from meza.fntools import Objectify
        >>> from itertools import repeat
        >>>
        >>> kwargs = {"field": "content", "dir": "desc"}
        >>> rule = Objectify(kwargs)
        >>> stream = ({"content": x} for x in range(5))
        >>> tuples = zip(stream, repeat(rule))
        >>> next(parser(stream, [rule], tuples, **kwargs))
        {'content': 4}

    """
    return reduce(reducer, list(reversed(rules)), stream)


@operator(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously sorts a stream according to a specified key.

    Not lazy: materializes the source and cannot be used on an unbounded stream.
    Listing several rules sorts by the first, breaking ties with the rest.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The sort criteria.

                (default: {"field": "content", "dir": "asc", "type": "text"}).

                field (str): Item attribute to sort on (default: "content").

                dir (str): The sort direction, either "asc" or "desc"
                    (default: "asc").

                type (str): Value type to compare as, one of "bool", "date",
                    "datetime", "decimal", "float", "int", "pass", "text", "url".
                    Values compare as strings when unset, so "10" sorts before
                    "9" (default: "text").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "sort").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     items = [{"rank": "b"}, {"rank": "a"}, {"rank": "c"}]
        ...     result = await async_pipe(items, conf={"rule": {"field": "rank"}})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'rank': 'a'}

    """
    return parser(*args, **kwargs)


@operator(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Sorts a stream according to a specified key.

    Not lazy: materializes the source and cannot be used on an unbounded stream.
    Listing several rules sorts by the first, breaking ties with the rest.

    Args:
        items (Items): The source stream.

        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The sort criteria.

                (default: {"field": "content", "dir": "asc", "type": "text"}).

                field (str): Item attribute to sort on (default: "content").

                dir (str): The sort direction, either "asc" or "desc"
                    (default: "asc").

                type (str): Value type to compare as, one of "bool", "date",
                    "datetime", "decimal", "float", "int", "pass", "text", "url".
                    Values compare as strings when unset, so "10" sorts before
                    "9" (default: "text").

        context (Context): the execution context

    Kwargs:
        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "sort").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Examples:
        >>> items = [
        ...     {"rank": "b", "name": "adam"},
        ...     {"rank": "a", "name": "sue"},
        ...     {"rank": "c", "name": "bill"}]
        >>> rule = {"field": "rank"}
        >>> next(pipe(items, conf={"rule": rule}))["rank"]
        'a'
        >>> rule = {"field": "name"}
        >>> next(pipe(items, conf={"rule": rule}))["name"]
        'adam'
        >>> rule = {"field": "name", "dir": "desc"}
        >>> next(pipe(items, conf={"rule": rule}))["name"]
        'sue'
        >>> tied = [
        ...     {"rank": "a", "name": "sue"},
        ...     {"rank": "a", "name": "bill"},
        ...     {"rank": "b", "name": "adam"}]
        >>> rules = [{"field": "rank"}, {"field": "name"}]
        >>> [i["name"] for i in pipe(tied, conf={"rule": rules})]
        ['bill', 'sue', 'adam']

    """
    return parser(*args, **kwargs)
