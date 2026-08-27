# vim: sw=4:ts=4:expandtab
r"""
Replaces text in item fields using regular expressions.

Search-and-replace on steroids. Each rule reads "in *field*, replace *match*
with *replace*", and several rules can run in sequence. Unlike most pipes, this
rewrites fields on the item itself rather than producing a separate value, so
rules may target different fields in one pass.

Examples:
    Basic usage::

        >>> from riko.modules.regex import pipe
        >>>
        >>> match = r"(\w+)\s(\w+)"
        >>> rule = {"field": "content", "match": match, "replace": "$2wide"}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf={"rule": rule}))["content"]
        'worldwide'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Sequence
from functools import reduce
from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko._iterutils import group_by
from riko._strutils import get_regex_rule, multi_substitute, substitute
from riko.bado.itertools import async_reduce, coop_reduce
from riko.dotdict import DotDict
from riko.types.configs import RegexObjconf
from riko.types.general import Defaults, Item, Opts
from riko.types.modules import RegexConfRule, RegexRule
from riko.types.values import MISSING, RikoValue

from . import processor

OPTS: Opts = {"listize": True, "extract": "rule", "emit": True}
DEFAULTS: Defaults = {"multi": False}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    item: Item,
    rules: Sequence[RegexConfRule],
    objconf: RegexObjconf,
    **kwargs: object,
) -> Item:
    """
    Asynchronously applies each rule to the field it names.

    Rules are grouped by field, so one pass can rewrite several fields.

    Args:
        item: The entry to process.
        rules: The parsed replacement rules.
        objconf: The pipe configuration, containing `multi`.

    Returns:
        The item with each named field rewritten.

    Examples:
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({"content": "hello world", "title": "greeting"})
        >>> match = r"(\\w+)\\s(\\w+)"
        >>> replace = "$2wide"
        >>>
        >>> async def main():
        ...     rule = {"field": "content", "match": match, "replace": replace}
        ...     conf = {"rule": rule, "multi": False}
        ...     objconf = Objectify(conf)
        ...     rules = [Objectify(rule)]
        ...     kwargs = {"stream": item, "conf": conf}
        ...     result = await async_parser(item, rules, objconf, **kwargs)
        ...     print(result["content"])
        >>>
        >>> run(main)
        worldwide

    """
    multi = objconf.multi
    recompile = not multi

    async def reducer(item: Item, rules: Sequence[RegexRule]) -> DotDict[RikoValue]:
        field = rules[0]["field"]
        word = item.get(field, MISSING, **kwargs)

        if word is MISSING or word is None:
            replacement = word
        elif multi:
            grouped = group_by(rules, "flags")
            group_rules = [g[1] for g in grouped]
            replacement = await coop_reduce(multi_substitute, group_rules, str(word))
        else:
            replacement = await coop_reduce(substitute, rules, str(word))

        rewritten = {} if replacement is MISSING else {field: replacement}
        result = DotDict({**item, **rewritten})
        return cast(DotDict[RikoValue], result)

    regex_rules = [get_regex_rule(r, recompile=recompile) for r in rules]
    grouped = group_by(regex_rules, "field")
    field_rules = [g[1] for g in grouped]
    return await async_reduce(reducer, field_rules, item)


def parser(
    item: Item,
    rules: Sequence[RegexConfRule],
    objconf: RegexObjconf,
    **kwargs: object,
) -> Item:
    """
    Applies each rule to the field it names.

    Rules are grouped by field, so one pass can rewrite several fields.

    Args:
        item: The entry to process.
        rules: The parsed replacement rules.
        objconf: The pipe configuration, containing `multi`.

    Returns:
        The item with each named field rewritten.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({"content": "hello world", "title": "greeting"})
        >>> match = r"(\\w+)\\s(\\w+)"
        >>> rule = {"field": "content", "match": match, "replace": "$2wide"}
        >>> conf = {"rule": rule, "multi": False}
        >>> objconf = Objectify(conf)
        >>> rules = [Objectify(rule)]
        >>> kwargs = {"stream": item, "conf": conf}
        >>> parser(item, rules, objconf, **kwargs)
        {'content': 'worldwide', 'title': 'greeting'}
        >>> conf["multi"] = True
        >>> parser(item, rules, objconf, **kwargs)
        {'content': 'worldwide', 'title': 'greeting'}

    """
    multi = objconf.multi
    recompile = not multi

    def reducer(item: Item, rules: Sequence[RegexRule]) -> DotDict[RikoValue]:
        field = str(rules[0]["field"])
        word = item.get(field, MISSING, **kwargs)

        if word is MISSING or word is None:
            replacement = word
        elif multi:
            grouped = group_by(rules, "flags")
            group_rules = [g[1] for g in grouped]
            replacement = reduce(multi_substitute, group_rules, str(word))
        else:
            replacement = reduce(substitute, rules, str(word))

        rewritten = {} if replacement is MISSING else {field: replacement}
        result = DotDict({**item, **rewritten})
        return cast(DotDict[RikoValue], result)

    regex_rules = [get_regex_rule(r, recompile=recompile) for r in rules]
    grouped = group_by(regex_rules, "field")
    field_rules = [g[1] for g in grouped]
    return reduce(reducer, field_rules, item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Item:
    """
    Asynchronously replaces text in item fields using regexes.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The replacement criteria. Required.

                field (str): Item attribute to rewrite.

                match (str): Regex to search for.

                replace (str): Replacement text. ``$1``, ``$2``, ... refer to
                    capture groups.

                default (str): Value to use when nothing matches (default:
                    None, i.e. keep the original).

                casematch (bool): Whether to match case sensitively
                    (default: False).

                singlelinematch (bool): Whether to replace only the first match
                    and confine ``^``, ``$`` and ``.`` to one line
                    (default: False).

                seriesmatch (bool): Whether to apply this rule in series with
                    the others (default: True).

            multi (bool): Whether to combine rules sharing a flag set into one
                pass (default: False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the rewritten item is nested under. Ignored when
            ``emit`` is True (default: "regex").

        emit (bool): Whether to emit the rewritten item directly rather than
            nest it. Overrides ``assign`` (default: True).

    Yields:
        - the rewritten ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        A rule naming a field the item lacks is skipped, leaving the item
        untouched.

    Examples:
        >>> from riko import run
        >>>
        >>> item = {"content": "hello world", "title": "greeting"}
        >>> match = r"(\\w+)\\s(\\w+)"
        >>>
        >>> async def main():
        ...     rule = {"field": "content", "match": match, "replace": "$2wide"}
        ...     conf = {"rule": rule, "multi": False}
        ...     result = await async_pipe(item, conf=conf)
        ...     print(next(result)["content"])
        >>>
        >>> run(main)
        worldwide

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Item:
    """
    Replaces text in item fields using regexes.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            rule (dict | list[dict]): The replacement criteria. Required.

                field (str): Item attribute to rewrite.

                match (str): Regex to search for.

                replace (str): Replacement text. ``$1``, ``$2``, ... refer to
                    capture groups.

                default (str): Value to use when nothing matches (default:
                    None, i.e. keep the original).

                casematch (bool): Whether to match case sensitively
                    (default: False).

                singlelinematch (bool): Whether to replace only the first match
                    and confine ``^``, ``$`` and ``.`` to one line
                    (default: False).

                seriesmatch (bool): Whether to apply this rule in series with
                    the others (default: True).

            multi (bool): Whether to combine rules sharing a flag set into one
                pass (default: False).

        context (Context): the execution context

    Kwargs:
        assign (str): Field the rewritten item is nested under. Ignored when
            ``emit`` is True (default: "regex").

        emit (bool): Whether to emit the rewritten item directly rather than
            nest it. Overrides ``assign`` (default: True).

    Yields:
        - the rewritten ``Item`` when ``emit`` is True (default)
        - ``{<assign>: Item}`` when ``emit`` is False

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        A rule naming a field the item lacks is skipped, leaving the item
        untouched.

    Examples:
        >>> # default matching
        >>> item = {"content": "hello world", "title": "greeting"}
        >>> match = r"(\\w+)\\s(\\w+)"
        >>> rule = {"field": "content", "match": match, "replace": "$2wide"}
        >>> conf = {"rule": rule, "multi": False}
        >>> next(pipe(item, conf=conf))
        {'content': 'worldwide', 'title': 'greeting'}
        >>> # multiple regex mode
        >>> conf["multi"] = True
        >>> next(pipe(item, conf=conf))
        {'content': 'worldwide', 'title': 'greeting'}
        >>> # case insensitive matching
        >>> item = {"content": "Hello hello"}
        >>> rule.update({"match": r"hello.*", "replace": "bye"})
        >>> next(pipe(item, conf=conf))["content"]
        'bye'
        >>> # case sensitive matching
        >>> rule["casematch"] = True
        >>> next(pipe(item, conf=conf))["content"]
        'Hello bye'

    """
    return parser(*args, **kwargs)
