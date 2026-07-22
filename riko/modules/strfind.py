# vim: sw=4:ts=4:expandtab
"""
Provides functions for finding text located before, after, at, or between
substrings.

Examples:
    basic usage::

        >>> from riko.modules.strfind import pipe
        >>>
        >>> conf = {'rule': {'find': 'o'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strfind']
        'hell'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Sequence
from functools import reduce

import pygogo as gogo

from riko.bado.itertools import coop_reduce
from riko.cast import BasicCastType
from riko.types.configs import StrfindObjconf
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
logger = gogo.Gogo(__name__, monolog=True).logger

PARAMS = {
    "first": lambda word, rule: word.split(rule.find, 1),
    "last": lambda word, rule: word.split(rule.find),
}

AT_PARAMS = {
    "first": lambda word, rule: word.find(rule.find),
    "last": lambda word, rule: word.rfind(rule.find),
}

OPS = {
    "before": lambda splits, rule: rule.find.join(splits[: len(splits) - 1]),
    "after": lambda splits, _: splits[-1],
    "at": lambda splits, _: splits,
}


def reducer(word, rule) -> str:
    default = rule.default or ""

    if rule.location == "at":
        result = AT_PARAMS.get(rule.param, AT_PARAMS["first"])(word, rule)
        splits = word[result : len(rule.find)] if result != -1 else default
    else:
        splits = PARAMS.get(rule.param, PARAMS["first"])(word, rule)

    return OPS.get(rule.location, OPS["before"])(splits, rule).strip()


async def async_parser(
    word: str, rules: Sequence[FindConfRule], objconf: StrfindObjconf, **kwargs
) -> str:
    """
    Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strfind)
        stream (dict): The original item

    Returns:
        Awaitable: item

    Examples:
        >>> from riko.bado import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': 'o'}}
        ...     rule = Objectify(conf['rule'])
        ...     result = await async_parser(item['content'], [rule], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        hell

    """
    return await coop_reduce(reducer, rules, word)


def parser(
    word: str, rules: Sequence[FindConfRule], objconf: StrfindObjconf, **kwargs
) -> str:
    """
    Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strfind)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'find': 'o'}}
        >>> rule = Objectify(conf['rule'])
        >>> args = item['content'], [rule], False
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> parser(*args, **kwargs)
        'hell'

    """
    return reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> str:
    """
    A processor module that asynchronously finds text within the field of an
    item.

    Args:
        item (dict): The entry to process
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

        assign (str): Attribute to assign parsed content (default: strfind)
        field (str): Item attribute from which to obtain the word to
            operate on (default: 'content')

    Returns:
       Awaitable: item with transformed content

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     conf = {'rule': {'find': 'o'}}
        ...     result = await async_pipe({'content': 'hello world'}, conf=conf)
        ...     print(next(result)['strfind'])
        >>>
        >>> run(main)
        hell

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> str:
    """
    A processor that finds text within the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'find'. May contain the keys  'location' or 'param'.

                find (str): The string to find.

                location (str): Direction of the substring to return. Must be
                    either 'before', 'after', or 'at' (default: 'before').

                param (str): The type of search. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: strfind)
        field (str): Item attribute from which to obtain the word to
            operate on (default: 'content')

    Yields:
        dict: an item with transformed content

    Examples:
        >>> conf = {'rule': {'find': 'o'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strfind']
        'hell'
        >>> conf = {'rule': {'find': 'w', 'location': 'after'}}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> item = {'title': 'hello world'}
        >>> next(pipe(item, **kwargs))['result']
        'orld'
        >>> conf = {
        ...     'rule': [
        ...         {'find': 'o', 'location': 'after', 'param': 'last'},
        ...         {'find': 'l'}]}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strfind']
        'r'

    """
    return parser(*args, **kwargs)
