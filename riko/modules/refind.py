# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.refind
~~~~~~~~~~~~~~~~~~~
Provides functions for finding text located before, after, or between
substrings using regular expressions, a powerful type of pattern matching.

Examples:
    basic usage::

        >>> from riko.modules.refind import pipe
        >>> conf = {'rule': {'find': '[aiou]'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind'] == 'hell'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re
import pygogo as gogo

from functools import reduce
from builtins import *

from . import processor
from riko.bado import coroutine, return_value, itertools as ait

OPTS = {
    'listize': True, 'ftype': 'text', 'field': 'content', 'extract': 'rule'}

DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger

PARAMS = {
    'first': lambda word, rule: re.split(rule.find, word, maxsplit=1),
    'last': lambda word, rule: re.split(rule.find, word)}

OPS = {
    'before': lambda splits, rule: rule.find.join(splits[:len(splits) - 1]),
    'after': lambda splits, rule: splits[-1]}


def reducer(word, rule):
    splits = PARAMS.get(rule.param, PARAMS['first'])(word, rule)

    if rule.param != 'last' and len(splits) > 2:
        joined = splits[:1] + [''.join(splits[1:])]
    else:
        joined = splits

    return OPS.get(rule.location, OPS['before'])(joined, rule).strip()


@coroutine
def async_parser(word, rules, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: refind)
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple of (item, skip)

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0])
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     rule = Objectify(conf['rule'])
        ...     kwargs = {'stream': item, 'conf': conf}
        ...     d = async_parser(item['content'], [rule], False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hell
    """
    if skip:
        value = kwargs['stream']
    else:
        value = yield ait.coop_reduce(reducer, rules, word)

    result = (value, skip)
    return_value(result)


def parser(word, rules, skip, **kwargs):
    """ Parses the pipe content

    Args:
        word (str): The string to transform
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: refind)
        stream (dict): The original item

    Returns:
        Tuple(dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'find': '[aiou]'}}
        >>> rule = Objectify(conf['rule'])
        >>> args = item['content'], [rule], False
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> parser(*args, **kwargs)[0] == 'hell'
        True
    """
    value = kwargs['stream'] if skip else reduce(reducer, rules, word)
    return value, skip


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor module that asynchronously finds text within the field of an
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
                    either 'before' or 'after' (default: 'before').

                param (str): The type of replacement. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with transformed content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['refind'])
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     d = async_pipe({'content': 'hello world'}, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hell
    """
    return async_parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that finds text within the field of an item using regex.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the key 'find'. May contain the keys 'location' or 'param'.

                find (str): The string to find.

                location (str): Direction of the substring to return. Must be
                    either 'before' or 'after' (default: 'before').

                param (str): The type of replacement. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute from which to obtain the first number to
            operate on (default: 'content')

    Yields:
        dict: an item with transformed content

    Examples:
        >>> conf = {'rule': {'find': '[aiou]'}}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind'] == 'hell'
        True
        >>> conf = {'rule': {'find': 'w', 'location': 'after'}}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> item = {'title': 'hello world'}
        >>> next(pipe(item, **kwargs))['result'] == 'orld'
        True
        >>> conf = {
        ...     'rule': [
        ...         {'find': 'o([a-z])', 'location': 'after'},
        ...         {'find': '[ld]'}]}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind'] == 'r'
        True
    """
    return parser(*args, **kwargs)
