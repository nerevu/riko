# vim: sw=4:ts=4:expandtab
"""
Provides functions for finding text located before, after, at, or between
substrings using regular expressions, a powerful type of pattern matching.

Examples:
    basic usage::

        >>> from riko.modules.refind import pipe
        >>>
        >>> rule = {'find': '[aiou]'}
        >>> conf = {'rule': rule}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind']
        'hell'
        >>> rule = {'find': '[aiou]', 'location': 'at'}
        >>> next(pipe(item, conf=conf))['refind']
        'hell'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import re
from collections.abc import Callable, Sequence
from functools import reduce
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.bado.itertools import coop_reduce
from riko.cast import BasicCastType
from riko.types.configs import RefindObjconf
from riko.types.general import Defaults, Opts
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

PARAMS: dict[str, Callable[[str, FindConfRule], list[str]]] = {
    "first": lambda word, rule: re.split(rule.find, word, maxsplit=1),
    "last": lambda word, rule: re.split(rule.find, word),
}

AT_PARAMS: dict[
    str, Callable[[str, FindConfRule], list[str] | re.Match[str] | None]
] = {
    "first": lambda word, rule: re.search(rule.find, word),
    "last": lambda word, rule: re.findall(rule.find, word),
}

OPS: dict[str, Callable[[list[str], FindConfRule], str]] = {
    "before": lambda splits, rule: rule.find.join(splits[: len(splits) - 1]),
    "after": lambda splits, _: splits[-1],
}


def reducer(word: str, rule: FindConfRule) -> str:
    param = rule.param or "first"
    is_first = param == "first"

    if rule.location == "at":
        result = ""
        splits = AT_PARAMS.get(param, AT_PARAMS["first"])(word, rule)

        if splits and is_first:
            result = splits[0]
        elif splits:
            result = splits[-1]
    else:
        splits = PARAMS.get(param, PARAMS["first"])(word, rule)
        result = OPS.get(rule.location, OPS["before"])(splits, rule)

    return result.strip()


async def async_parser(
    word: str, rules: Sequence[FindConfRule], objconf: RefindObjconf, **kwargs: object
) -> str:
    """
    Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: refind)
        stream (dict): The original item

    Returns:
        Awaitable: item

    Examples:
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     rule = Objectify(conf['rule'])
        ...     result = await async_parser(item['content'], [rule], None, stream=item)
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
    Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: refind)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'find': '[aiou]'}}
        >>> rule = Objectify(conf['rule'])
        >>> parser(item['content'], [rule], None, stream=item)
        'hell'

    """
    return reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    A processor module that asynchronously finds text within the field of an
    item using regex.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'find'. May contain the keys 'location' or 'param'.

                find (str): The string to find.

                location (str): Direction of the substring to return. Must be
                    either 'before', 'after', or 'at' (default: 'before').

                param (str): The type of search. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Awaitable: item with transformed content

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     result = await async_pipe({'content': 'hello world'}, conf=conf)
        ...     print(next(result)['refind'])
        >>>
        >>> run(main)
        hell

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    A processor that finds text within the field of an item using regex.

    Args:
        item (dict or Iter[dict]): The entry, or stream of entries, to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'find'. May contain the keys 'location' or 'param'.

                find (str): The string to find.

                location (str): Direction of the substring to return. Must be
                    either 'before', 'after', or 'at' (default: 'before').

                param (str): The type of search. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with transformed content

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Examples:
        >>> conf = {'rule': {'find': '[aiou]'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind']
        'hell'
        >>> conf = {'rule': {'find': 'w', 'location': 'after'}}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> item = {'title': 'hello world'}
        >>> next(pipe(item, **kwargs))['result']
        'orld'
        >>> conf = {
        ...     'rule': [
        ...         {'find': 'o([a-z])', 'location': 'after'}, {'find': 'd'}]}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind']
        'l'

    """
    return parser(*args, **kwargs)
