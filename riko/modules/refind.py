# vim: sw=4:ts=4:expandtab
"""
Finds text before, after, or at a regex match.

``location`` picks which side of the match to keep and ``param`` picks which
match to measure from, so one ``find`` covers several extractions.

Examples:
    Basic usage::

        >>> from riko.modules.refind import pipe
        >>>
        >>> item = {"content": "hello world"}
        >>> rule = {"find": "[aiou]"}
        >>> next(pipe(item, conf={"rule": rule}))["refind"]
        'hell'
        >>> rule["location"] = "at"
        >>> next(pipe(item, conf={"rule": rule}))["refind"]
        'o'
        >>> rule["location"] = "after"
        >>> next(pipe(item, conf={"rule": rule}))["refind"]
        'world'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Sequence
from functools import reduce
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._strutils import reduce_find
from riko.bado.itertools import coop_reduce
from riko.cast import BasicCastType
from riko.types._configs import RefindObjconf
from riko.types._options import Defaults, Opts
from riko.types.modules import FindConfRule

from . import processor

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "listize": True,
    "field": "content",
    "extract": "rule",
}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def reducer(word: str, rule: FindConfRule) -> str:
    return reduce_find(word, rule)


async def async_parser(
    word: str, rules: Sequence[FindConfRule], objconf: RefindObjconf, **kwargs: object
) -> str:
    """
    Asynchronously applies each rule to ``word``.

    Each rule narrows the result of the previous one, so rules chain.

    Args:
        word: The string to search.
        rules: The parsed find rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The extracted stripped text, or ``""`` if nothing matches.

    Examples:
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {"content": "hello world"}
        ...     conf = {"rule": {"find": "[aiou]"}}
        ...     rule = Objectify(conf["rule"])
        ...     result = await async_parser(item["content"], [rule], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        hell

    """
    return await coop_reduce(reducer, rules, word)


def parser(
    word: str, rules: Sequence[FindConfRule], objconf: RefindObjconf, **kwargs: object
) -> str:
    """
    Applies each rule to ``word``.

    Each rule narrows the result of the previous one, so rules chain.

    Args:
        word: The string to search.
        rules: The parsed find rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The extracted stripped text, or ``""`` if nothing matches.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "hello world"}
        >>> conf = {"rule": {"find": "[aiou]"}}
        >>> rule = Objectify(conf["rule"])
        >>> parser(item["content"], [rule], None, stream=item)
        'hell'

    """
    return reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously finds text before, after, or at a regex match.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The find criteria. Required.

                find (str): Regex to search for.

                location (str): Which side of the match to keep, one of
                    "before", "after", "at" (default: "before").

                param (str): Which match to measure from, either "first" or
                    "last" (default: "first").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to search (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "refind").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        Yields ``""`` if nothing matches, except ``location="after"`` which yields
        the whole field.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"rule": {"find": "[aiou]"}}
        ...     result = await async_pipe({"content": "hello world"}, conf=conf)
        ...     print(next(result)["refind"])
        >>>
        >>> run(main)
        hell

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Finds text before, after, or at a regex match.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The find criteria. Required.

                find (str): Regex to search for.

                location (str): Which side of the match to keep, one of
                    "before", "after", "at" (default: "before").

                param (str): Which match to measure from, either "first" or
                    "last" (default: "first").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to search (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "refind").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        Yields ``""`` if nothing matches, except ``location="after"`` which yields
        the whole field.

    Examples:
        >>> conf = {"rule": {"find": "[aiou]"}}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["refind"]
        'hell'
        >>> conf = {"rule": {"find": "w", "location": "after"}}
        >>> kwargs = {"conf": conf, "field": "title", "assign": "result"}
        >>> item = {"title": "hello world"}
        >>> next(pipe(item, **kwargs))["result"]
        'orld'
        >>> rules = [{"find": "o([a-z])", "location": "after"}, {"find": "d"}]
        >>> conf = {"rule": rules}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["refind"]
        'l'

    """
    return parser(*args, **kwargs)
