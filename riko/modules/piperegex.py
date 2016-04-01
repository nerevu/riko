# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.piperegex
~~~~~~~~~~~~~~~~~~~~~~
Provides functions for modifying the content of a field of a feed item using
regular expressions, a powerful type of pattern matching.

Think of it as search-and-replace on steriods. You can define multiple Regex
rules. Each has the general format: "In [field] replace [regex pattern] with
[text]".

Examples:
    basic usage::

        >>> from riko.modules.piperegex import pipe
        >>>
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule}
        >>> next(pipe({'content': 'hello world'}, conf=conf))['content']
        u'worldwide'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import reduce

from builtins import *
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils
from riko.lib.utils import combine_dicts as cdicts
from riko.lib.log import Logger
from riko.twisted import utils as tu
from riko.lib.dotdict import DotDict

OPTS = {'listize': True, 'extract': 'rule', 'emit': True}
DEFAULTS = {'convert': True, 'multi': False}
logger = Logger(__name__).logger


@inlineCallbacks
def asyncParser(item, rules, skip, **kwargs):
    """ Asynchronously parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Deferred: twisted.internet.defer.Deferred Tuple(dict, bool)

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\w+)\s(\w+)'
        >>> replace = '$2wide'
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x[0]['content'])
        ...     rule = {'field': 'content', 'match': match, 'replace': replace}
        ...     conf = {'rule': rule, 'multi': False, 'convert': True}
        ...     rules = [Objectify(rule)]
        ...     kwargs = {'feed': item, 'conf': conf}
        ...     d = asyncParser(item, rules, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        worldwide
    """
    multi = kwargs['conf']['multi']
    recompile = not multi

    @inlineCallbacks
    def asyncReducer(item, rules):
        field = rules[0]['field']
        word = item.get(field, **kwargs)
        grouped = utils.group_by(rules, 'flags')
        group_rules = [g[1] for g in grouped] if multi else rules
        reducer = utils.multi_substitute if multi else utils.substitute
        replacement = yield tu.coopReduce(reducer, group_rules, word)
        combined = cdicts(item, {field: replacement})
        returnValue(DotDict(combined))

    if skip:
        item = kwargs['feed']
    else:
        new_rules = [utils.get_new_rule(r, recompile=recompile) for r in rules]
        grouped = utils.group_by(new_rules, 'field')
        field_rules = [g[1] for g in grouped]
        item = yield tu.asyncReduce(asyncReducer, field_rules, item)

    result = (item, skip)
    returnValue(result)


def parser(item, rules, skip, **kwargs):
    """ Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        rules (List[obj]): the parsed rules (Objectify instances).
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple (dict, bool): Tuple of (item, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>>
        >>> item = DotDict({'content': 'hello world', 'title': 'greeting'})
        >>> match = r'(\w+)\s(\w+)'
        >>> rule = {'field': 'content', 'match': match, 'replace': '$2wide'}
        >>> conf = {'rule': rule, 'multi': False, 'convert': True}
        >>> rules = [Objectify(rule)]
        >>> kwargs = {'feed': item, 'conf': conf}
        >>> regexed, skip = parser(item, rules, False, **kwargs)
        >>> regexed == {'content': 'worldwide', 'title': 'greeting'}
        True
        >>> conf['multi'] = True
        >>> parser(item, rules, False, **kwargs)[0] == regexed
        True
    """
    multi = kwargs['conf']['multi']
    recompile = not multi

    def meta_reducer(item, rules):
        field = rules[0]['field']
        word = item.get(field, **kwargs)
        grouped = utils.group_by(rules, 'flags')
        group_rules = [g[1] for g in grouped] if multi else rules
        reducer = utils.multi_substitute if multi else utils.substitute
        replacement = reduce(reducer, group_rules, word)
        return DotDict(cdicts(item, {field: replacement}))

    if skip:
        item = kwargs['feed']
    else:
        new_rules = [utils.get_new_rule(r, recompile=recompile) for r in rules]
        grouped = utils.group_by(new_rules, 'field')
        field_rules = [g[1] for g in grouped]
        item = reduce(meta_reducer, field_rules, item)

    return item, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor that asynchronously replaces text in fields of a feed item
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
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>>
        >>> item = {'content': 'hello world', 'title': 'greeting'}
        >>> match = r'(\w+)\s(\w+)'
        >>> replace = '$2wide'
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['content'])
        ...     rule = {'field': 'content', 'match': match, 'replace': replace}
        ...     conf = {'rule': rule, 'multi': False, 'convert': True}
        ...     d = asyncPipe(item, conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        worldwide
    """
    return asyncParser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that replaces text in fields of a feed item using regexes.

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
        >>> result == {'content': u'worldwide', 'title': 'greeting'}
        True
        >>> # multiple regex mode
        >>> conf['multi'] = True
        >>> next(pipe(item, conf=conf)) == result
        True
        >>> # case insensitive matching
        >>> item = {'content': 'Hello hello'}
        >>> rule.update({'match': r'hello.*', 'replace': 'bye'})
        >>> next(pipe(item, conf=conf))['content']
        u'bye'
        >>> # case sensitive matching
        >>> rule['casematch'] = True
        >>> next(pipe(item, conf=conf))['content']
        u'Hello bye'
    """
    return parser(*args, **kwargs)
