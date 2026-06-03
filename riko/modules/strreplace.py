# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.strreplace
~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for string search-and-replace.

You provide the module with the text string to search for, and what to replace
it with. Multiple search-and-replace pairs can be added. You can specify to
replace all occurrences of the search string, just the first occurrence, or the
last occurrence.

Examples:
    basic usage::

        >>> from riko.modules.strreplace import pipe
        >>>
        >>> conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strreplace']
        'bye world'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from typing import Sequence

import pygogo as gogo

from functools import reduce

from riko import Objconf
from riko.types.general import ItemArg, ObjconfRule

from . import processor
from riko.bado import coroutine, return_value, itertools as ait

OPTS = {"ftype": "text", "listize": True, "field": "content", "extract": "rule"}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger

OPS = {
    "first": lambda word, rule: word.replace(rule.find, rule.replace, 1),
    "last": lambda word, rule: rule.replace.join(word.rsplit(rule.find, 1)),
    "every": lambda word, rule: word.replace(rule.find, rule.replace),
}


def reducer(word, rule):
    return OPS.get(rule.param, OPS["every"])(word, rule)


@coroutine  # pyright: ignore[reportArgumentType]
def async_parser(word: str, rules: Sequence[ObjconfRule], objconf: Objconf, skip=False, **kwargs):
    """Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strreplace)
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        ...     rule = Objectify(conf['rule'])
        ...     d = async_parser(item['content'], [rule], None, stream=item)
        ...     return d.addCallbacks(print, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        bye world
    """
    if skip:
        value = kwargs["stream"]
    else:
        value = yield ait.coop_reduce(reducer, rules, word)  # pyright: ignore[reportCallIssue]

    return_value(value)


def parser(word: str, rules: Sequence[ObjconfRule], objconf: Objconf, skip=False, **kwargs) -> ItemArg:
    """Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: strtransform)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        >>> rule = Objectify(conf['rule'])
        >>> parser(item['content'], [rule], None, stream=item)
        'bye world'
    """
    return kwargs["stream"] if skip else reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously replaces the text of a field of
    an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'find' and 'replace'. May contain the key 'param'.

                find (str): The string to find.
                replace (str): The string replacement.
                param (str): The type of replacement. Must be one of: 'first',
                    'last', or 'every' (default: 'every').

        assign (str): Attribute to assign parsed content (default: strreplace)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with replaced content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['strreplace'])
        ...     conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        ...     d = async_pipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        bye world
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that replaces the text of a field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'find' and 'replace'. May contain the key 'param'.

                find (str): The string to find.
                replace (str): The string replacement.
                param (str): The type of replacement. Must be one of: 'first',
                    'last', or 'every' (default: 'every').

        assign (str): Attribute to assign parsed content (default: strreplace)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with replaced content

    Examples:
        >>> conf = {'rule': {'find': 'hello', 'replace': 'bye'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['strreplace']
        'bye world'
        >>> rules = [
        ...     {'find': 'Gr', 'replace': 'M'},
        ...     {'find': 'e', 'replace': 'a', 'param': 'last'}]
        >>> conf = {'rule': rules}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> item = {'title': 'Greetings'}
        >>> next(pipe(item, **kwargs))['result']
        'Meatings'
    """
    return parser(*args, **kwargs)
