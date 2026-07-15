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
from collections.abc import Sequence
from functools import reduce

import pygogo as gogo

from riko import Objconf
from riko.bado import itertools as ait
from riko.cast import BasicCastType
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
    "first": lambda word, rule: re.split(rule.find, word, maxsplit=1),
    "last": lambda word, rule: re.split(rule.find, word),
}

AT_PARAMS = {
    "first": lambda word, rule: re.search(rule.find, word),
    "last": lambda word, rule: re.findall(rule.find, word),
}

OPS = {
    "before": lambda splits, rule: rule.find.join(splits[: len(splits) - 1]),
    "after": lambda splits, _: splits[-1],
    "at": lambda splits, _: splits,
}


def reducer(word, rule) -> str:
    param = rule.param or "first"
    default = rule.default or ""

    if rule.location == "at":
        result = AT_PARAMS.get(param, AT_PARAMS["first"])(word, rule)

        if result and param == "first":
            splits = result.group(0)
        elif result and param == "last":
            splits = result[-1]
        else:
            splits = default
    else:
        splits = PARAMS.get(param, PARAMS["first"])(word, rule)

    return OPS.get(rule.location, OPS["before"])(splits, rule).strip()


async def async_parser(
    word: str, rules: Sequence[FindConfRule], objconf: Objconf, **kwargs
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
        Deferred: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> async def run(reactor):
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     rule = Objectify(conf['rule'])
        ...     result = await async_parser(item['content'], [rule], None, stream=item)
        ...     print(result)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hell

    """
    value = await ait.coop_reduce(reducer, rules, word)
    return value


def parser(word: str, rules: Sequence[FindConfRule], objconf: Objconf, **kwargs) -> str:
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
async def async_pipe(*args, **kwargs) -> str:
    """
    A processor module that asynchronously finds text within the field of an
    item using regex.

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

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with transformed content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     result = await async_pipe({'content': 'hello world'}, conf=conf)
        ...     print(next(result)['refind'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hell

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> str:
    """
    A processor that finds text within the field of an item using regex.

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

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with transformed content

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
