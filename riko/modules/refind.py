# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.refind
~~~~~~~~~~~~~~~~~~~
Provides functions for finding text located before, after, at, or between
substrings using regular expressions, a powerful type of pattern matching.

Examples:
    basic usage::

        >>> from riko.modules.refind import pipe
        >>>
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
from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.bado import coroutine, return_value, itertools as ait

OPTS = {
    'listize': True, 'ftype': 'text', 'field': 'content', 'extract': 'rule'}

DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger

PARAMS = {
    'first': lambda word, rule: re.split(rule.find, word, maxsplit=1),
    'last': lambda word, rule: re.split(rule.find, word)}

AT_PARAMS = {
    'first': lambda word, rule: re.search(rule.find, word),
    'last': lambda word, rule: re.findall(rule.find, word)}

OPS = {
    'before': lambda splits, rule: rule.find.join(splits[:len(splits) - 1]),
    'after': lambda splits, rule: splits[-1],
    'at': lambda splits, rule: splits,
}


def reducer(word, rule):
    param = rule.param or 'first'
    default = rule.default or ''

    if rule.location == 'at':
        result = AT_PARAMS.get(param, AT_PARAMS['first'])(word, rule)

        if result and param == 'first':
            splits = result.group(0)
        elif result and param == 'last':
            splits = result[-1]
        else:
            splits = default
    else:
        splits = PARAMS.get(param, PARAMS['first'])(word, rule)

    return OPS.get(rule.location, OPS['before'])(splits, rule).strip()


@coroutine
def async_parser(word, rules, skip=False, **kwargs):
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
        Deferred: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     item = {'content': 'hello world'}
        ...     conf = {'rule': {'find': '[aiou]'}}
        ...     rule = Objectify(conf['rule'])
        ...     kwargs = {'stream': item, 'conf': conf}
        ...     d = async_parser(item['content'], [rule], **kwargs)
        ...     return d.addCallbacks(print, logger.error)
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

    return_value(value)


def parser(word, rules, skip=False, **kwargs):
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
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> conf = {'rule': {'find': '[aiou]'}}
        >>> rule = Objectify(conf['rule'])
        >>> args = item['content'], [rule], False
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> parser(*args, **kwargs) == 'hell'
        True
    """
    return kwargs['stream'] if skip else reduce(reducer, rules, word)


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
                    either 'before', 'after', or 'at' (default: 'before').

                param (str): The type of replacement. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute to operate on (default: 'content')

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
                    either 'before', 'after', or 'at' (default: 'before').

                param (str): The type of replacement. Must be either 'first'
                    or 'last' (default: 'first').

        assign (str): Attribute to assign parsed content (default: refind)
        field (str): Item attribute to operate on (default: 'content')

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
        ...         {'find': 'o([a-z])', 'location': 'after'}, {'find': 'd'}]}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['refind'] == 'l'
        True
    """
    return parser(*args, **kwargs)
