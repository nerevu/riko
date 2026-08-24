# vim: sw=4:ts=4:expandtab
"""
Replaces a literal substring in an item field.

Give it the text to search for and what to replace it with. Several rules can
be listed; each runs on the previous one's result. ``param`` selects whether to
replace every occurrence, just the first, or just the last.

Examples:
    Basic usage::

        >>> from riko.modules.strreplace import pipe
        >>>
        >>> conf = {"rule": {"find": "hello", "replace": "bye"}}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["strreplace"]
        'bye world'

Attributes:
    OPS: Replacement strategies, keyed by ``param``.
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Callable, Sequence
from functools import reduce
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.bado.itertools import coop_reduce
from riko.cast import BasicCastType
from riko.types.configs import StrReplaceObjconf
from riko.types.general import Defaults, Opts
from riko.types.modules import StrReplaceConfRule

from . import processor

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "listize": True,
    "field": "content",
    "extract": "rule",
}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger

OPS: dict[str, Callable[[str, StrReplaceConfRule], str]] = {
    "first": lambda word, rule: word.replace(rule.find, rule.replace, 1),
    "last": lambda word, rule: rule.replace.join(word.rsplit(rule.find, 1)),
    "every": lambda word, rule: word.replace(rule.find, rule.replace),
}


def reducer(word: str, rule: StrReplaceConfRule) -> str:
    return OPS.get(rule.param, OPS["every"])(word, rule)


async def async_parser(
    word: str,
    rules: Sequence[StrReplaceConfRule],
    objconf: StrReplaceObjconf,
    **kwargs: object,
) -> str:
    """
    Asynchronously applies each replacement rule to ``word``.

    Args:
        word: The string to transform.
        rules: The parsed replacement rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The transformed string, unchanged where nothing matched.

    Examples:
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {"content": "hello world"}
        ...     conf = {"rule": {"find": "hello", "replace": "bye"}}
        ...     rule = Objectify(conf["rule"])
        ...     result = await async_parser(item["content"], [rule], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        bye world

    """
    return await coop_reduce(reducer, rules, word)


def parser(
    word: str,
    rules: Sequence[StrReplaceConfRule],
    objconf: StrReplaceObjconf,
    **kwargs: object,
) -> str:
    """
    Applies each replacement rule to ``word``.

    Args:
        word: The string to transform.
        rules: The parsed replacement rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The transformed string, unchanged where nothing matched.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "hello world"}
        >>> conf = {"rule": {"find": "hello", "replace": "bye"}}
        >>> rule = Objectify(conf["rule"])
        >>> parser(item["content"], [rule], None, stream=item)
        'bye world'

    """
    return reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously replaces a literal substring in an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The replacement criteria. Required.

                find (str): Literal substring to replace.
                replace (str): Text to put in its place.

                param (str): Which occurrences to replace, one of "every",
                    "first", "last". An unrecognized value replaces every
                    occurrence (default: "every").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to search (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "strreplace").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"rule": {"find": "hello", "replace": "bye"}}
        ...     result = await async_pipe({"content": "hello world"}, conf=conf)
        ...     print(next(result)["strreplace"])
        >>>
        >>> run(main)
        bye world

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Replaces a literal substring in an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The replacement criteria. Required.

                find (str): Literal substring to replace.
                replace (str): Text to put in its place.

                param (str): Which occurrences to replace, one of "every",
                    "first", "last". An unrecognized value replaces every
                    occurrence (default: "every").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to search (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "strreplace").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <text>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <text>}`` when ``emit`` is False and no item given
        - ``<text>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Examples:
        >>> conf = {"rule": {"find": "hello", "replace": "bye"}}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["strreplace"]
        'bye world'
        >>> rules = [
        ...     {"find": "Gr", "replace": "M"},
        ...     {"find": "e", "replace": "a", "param": "last"}]
        >>> conf = {"rule": rules}
        >>> kwargs = {"conf": conf, "field": "title", "assign": "result"}
        >>> item = {"title": "Greetings"}
        >>> next(pipe(item, **kwargs))["result"]
        'Meatings'

    """
    return parser(*args, **kwargs)
