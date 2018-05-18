# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.regex
~~~~~~~~~~~~~~~~~~
Provides functions for modifying the content of a field of an item using
regular expressions, a powerful type of pattern matching.

Think of it as search-and-replace on steriods. You can define multiple Regex
rules. Each has the general format: "In [field] replace [regex pattern] with
[text]".

Examples:
    basic usage::

        >>> from riko.modules.regex import pipe
        >>>
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule}
        >>> item = {'content': 'hello world'}
        >>> next(pipe(item, conf=conf))['content'] == 'worldwide'
        True

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from functools import reduce
from builtins import *  # noqa pylint: disable=unused-import

from . import processor
from riko.utils import get_new_rule, substitute, multi_substitute, group_by
from riko.bado import coroutine, return_value, itertools as ait
from riko.dotdict import DotDict
from meza.process import merge

OPTS = {'listize': True, 'extract': 'rule', 'emit': True}
DEFAULTS = {'convert': True, 'multi': False}
logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine
def async_parser(item, rules, skip=False, **kwargs):
    """ Asynchronously parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred dict

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\w+)\s(\w+)'
        >>> replace = '$2wide'
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x['content'])
        ...     rule = {'field': 'content', 'match': match, 'replace': replace}
        ...     conf = {'rule': rule, 'multi': False, 'convert': True}
        ...     rules = [Objectify(rule)]
        ...     kwargs = {'stream': item, 'conf': conf}
        ...     d = async_parser(item, rules, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        worldwide
    """
    multi = kwargs['conf']['multi']
    recompile = not multi

    @coroutine
    def async_reducer(item, rules):
        field = rules[0]['field']
        word = item.get(field, **kwargs)
        grouped = group_by(rules, 'flags')
        group_rules = [g[1] for g in grouped] if multi else rules
        reducer = multi_substitute if multi else substitute
        replacement = yield ait.coop_reduce(reducer, group_rules, word)
        combined = merge([item, {field: replacement}])
        return_value(DotDict(combined))

    if skip:
        item = kwargs['stream']
    else:
        new_rules = [get_new_rule(r, recompile=recompile) for r in rules]
        grouped = group_by(new_rules, 'field')
        field_rules = [g[1] for g in grouped]
        item = yield ait.async_reduce(async_reducer, field_rules, item)

    return_value(item)


def parser(item, rules, skip=False, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> rules = [Objectify(rule)]
        >>> kwargs = {'stream': item, 'conf': conf}
        >>> regexed = parser(item, rules, **kwargs)
        >>> regexed == {'content': 'worldwide', 'title': 'greeting'}
        True
        >>> conf['multi'] = True
        >>> parser(item, rules, **kwargs) == regexed
        True
    """
    multi = kwargs['conf']['multi']
    recompile = not multi

    def meta_reducer(item, rules):
        field = rules[0]['field']
        word = item.get(field, **kwargs)
        grouped = group_by(rules, 'flags')
        group_rules = [g[1] for g in grouped] if multi else rules
        reducer = multi_substitute if multi else substitute
        replacement = reduce(reducer, group_rules, word)
        return DotDict(merge([item, {field: replacement}]))

    if skip:
        item = kwargs['stream']
    else:
        new_rules = [get_new_rule(r, recompile=recompile) for r in rules]
        grouped = group_by(new_rules, 'field')
        field_rules = [g[1] for g in grouped]
        item = reduce(meta_reducer, field_rules, item)

    return item


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs):
    """A processor that asynchronously replaces text in fields of an item
    using regexes.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'multi' or 'convert'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'match', and 'replace'.

                field (str): The item attribute to search
                match (str): The regex to apply
                replace (str): The string replacement
                default (str): Default if search pattern isn't found (
                    default: None, i.e, return the original string)

                singlematch (bool): Stop after first match (default: False)
                singlelinematch (bool): Don't search across newlines with '^',
                    '$', or '.' (default: False)

                casematch (bool): Perform case sensitive match (default: False)

            multi (bool): Efficiently combine multiple regexes (default: False)
            convert (bool): Convert regex into a Python compatible format
                (default: True)

    Yields:
        Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> item = {'content': 'hello world', 'title': 'greeting'}
        >>> match = r'(\w+)\s(\w+)'
        >>> replace = '$2wide'
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['content'])
        ...     rule = {'field': 'content', 'match': match, 'replace': replace}
        ...     conf = {'rule': rule, 'multi': False, 'convert': True}
        ...     d = async_pipe(item, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        worldwide
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that replaces text in fields of an item using regexes.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'rule'. May
            contain the keys 'multi' or 'convert'.

            rule (dict): can be either a dict or list of dicts. Must contain
                the keys 'field', 'match', and 'replace'.

                field (str): The item attribute to search
                match (str): The regex to apply
                replace (str): The string replacement
                default (str): Default if search pattern isn't found (
                    default: None, i.e, return the original string)

                singlematch (bool): Stop after first match (default: False)
                singlelinematch (bool): Don't search across newlines with '^',
                    '$', or '.' (default: False)

                casematch (bool): Perform case sensitive match (default: False)

            multi (bool): Efficiently combine multiple regexes (default: False)
            convert (bool): Convert regex into a Python compatible format
                (default: True)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> # default matching
        >>> item = {'content': 'hello world', 'title': 'greeting'}
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> result = next(pipe(item, conf=conf))
        >>> result == {'content': 'worldwide', 'title': 'greeting'}
        True
        >>> # multiple regex mode
        >>> conf['multi'] = True
        >>> next(pipe(item, conf=conf)) == result
        True
        >>> # case insensitive matching
        >>> item = {'content': 'Hello hello'}
        >>> rule.update({'match': r'hello.*', 'replace': 'bye'})
        >>> next(pipe(item, conf=conf))['content'] == 'bye'
        True
        >>> # case sensitive matching
        >>> rule['casematch'] = True
        >>> next(pipe(item, conf=conf))['content'] == 'Hello bye'
        True
    """
    return parser(*args, **kwargs)
